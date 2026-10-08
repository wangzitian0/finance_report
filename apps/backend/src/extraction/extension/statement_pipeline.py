"""Config-gated dispatch for the upload→report async pipeline (EPIC-019).

The upload→report background work is migrating from an in-process
``asyncio.create_task`` (fire-and-forget, lost on restart, competes with the API
process) to durable Prefect flow runs. This module is the seam:

- ``PREFECT_API_URL`` unset (CI / local / preview-without-Prefect) → fall back to
  the existing in-process ``asyncio.create_task``. Zero Prefect dependency: the
  app boots and tests run without any Prefect server (delivery speed unaffected).
- ``PREFECT_API_URL`` set (staging / prod, and the per-PR ephemeral Prefect) →
  submit a flow run to the Prefect server; an isolated worker (running this same
  backend image) executes ``parse_statement_flow``.

``prefect`` is imported lazily here even though it's a base dependency (not an
optional extra — the repo's promote-not-rebuild release model ships one image
everywhere), so the fallback path never pays an import cost it doesn't need.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.database import create_session_maker_from_db
from src.extraction.base.types import ParseJob
from src.observability import get_logger, run_with_async_parse_tracking

logger = get_logger(__name__)
settings = src.config.settings

# Prefect deployment name "<flow-name>/<deployment-name>".
PARSE_DEPLOYMENT = "parse-statement/parse-statement"


def compose_statement_ingestion_use_case(*, session_maker):
    """Lazy composition import avoids an extraction-package import cycle."""
    from src.composition import compose_statement_ingestion_use_case as compose

    return compose(session_maker=session_maker)


def _consume_background_task_exception(task: asyncio.Task[None]) -> None:
    """Retrieve fallback task exceptions after structured telemetry logs them."""
    try:
        task.exception()
    except asyncio.CancelledError:
        return


async def submit_parse_pipeline(
    *,
    job: ParseJob,
    content: bytes,
    db: AsyncSession,
) -> asyncio.Task[None] | None:
    """Dispatch statement parsing.

    Returns the in-process ``asyncio.Task`` for the caller to track in fallback
    mode, or ``None`` when the work was submitted to Prefect.

    Note: in Prefect mode ``content`` is not sent to the worker (it re-fetches
    from ``storage_key``). Avoiding the caller's pre-download in that mode is a
    P1 optimization deferred until the worker lands; in P0 (fallback only) the
    content is needed in-process anyway.
    """

    def _run_in_process() -> asyncio.Task[None]:
        use_case = compose_statement_ingestion_use_case(session_maker=create_session_maker_from_db(db))
        task = asyncio.create_task(
            run_with_async_parse_tracking(
                use_case.execute(job, content=content),
                statement_id=job.statement_id,
                request_id=job.request_id,
            )
        )
        task.add_done_callback(_consume_background_task_exception)
        return task

    if settings.prefect_api_url:
        # Remote durable execution. Only serializable params cross the boundary
        # (no raw bytes, no session maker): the worker re-fetches ``content``
        # from storage and builds its own DB session.
        try:
            from prefect.deployments import run_deployment  # lazy: fallback never imports prefect

            await run_deployment(
                name=PARSE_DEPLOYMENT,
                parameters={"job": job.to_prefect_params()},
                timeout=0,  # fire-and-submit: do not block the upload request on completion
            )
            logger.info(
                "statement.parse.submitted_to_prefect",
                statement_id=str(job.statement_id),
                deployment=PARSE_DEPLOYMENT,
                request_id=job.request_id,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            # Fail-soft: the managed Prefect is opt-in durability, never a hard
            # dependency. If the client isn't installed (ImportError on the base
            # image) or the server is unreachable / the submit fails, degrade to
            # in-process so an upload NEVER 500s on a Prefect issue. The work still
            # runs; only the durable-handoff is skipped (logged loudly for ops).
            logger.warning(
                "statement.parse.prefect_unavailable_fallback_in_process",
                statement_id=str(job.statement_id),
                error=str(exc),
                request_id=job.request_id,
            )
            return _run_in_process()

    return _run_in_process()


async def check_and_recover_stalled_parsing_jobs(
    db: AsyncSession,
    stall_threshold_seconds: int = 180,
) -> list[str]:
    """Recover statement parsing jobs stalled longer than threshold.

    Transitions status to REJECTED and records audit logging so the user
    can retry without waiting for supervisor reset.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from src.extraction.base.source_vocabulary import BankStatementStatus
    from src.extraction.orm.statement_summary import StatementSummary

    cutoff = datetime.now(UTC) - timedelta(seconds=stall_threshold_seconds)
    stmt = (
        select(StatementSummary)
        .where(StatementSummary.status == BankStatementStatus.PARSING)
        .where(StatementSummary.updated_at < cutoff)
    )
    result = await db.execute(stmt)
    stalled_statements = result.scalars().all()

    recovered_ids: list[str] = []
    for statement in stalled_statements:
        statement.status = BankStatementStatus.REJECTED
        statement.validation_error = "Parsing timed out after stall threshold. Please retry."
        statement.confidence_score = 0
        statement.balance_validated = False
        recovered_ids.append(str(statement.id))
        logger.warning(
            "statement.parsing.watchdog_timeout",
            statement_id=str(statement.id),
            stall_seconds=stall_threshold_seconds,
            updated_at=str(statement.updated_at),
        )

    if stalled_statements:
        await db.commit()

    return recovered_ids
