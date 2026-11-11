"""Config-gated dispatch for the upload-to-report async pipeline (EPIC-019)."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.database import create_session_maker_from_db
from src.extraction.base.types import ParseJob
from src.observability import get_logger, run_with_async_parse_tracking

logger = get_logger(__name__)
settings = src.config.settings

PARSE_DEPLOYMENT = "parse-statement/parse-statement"


def compose_statement_ingestion_use_case(*, session_maker):
    from src.composition import compose_statement_ingestion_use_case as compose

    return compose(session_maker=session_maker)


def _consume_background_task_exception(task: asyncio.Task[None]) -> None:
    with suppress(asyncio.CancelledError):
        task.exception()


async def submit_parse_pipeline(
    *,
    job: ParseJob,
    content: bytes,
    db: AsyncSession,
) -> asyncio.Task[None] | None:
    """Dispatch statement parsing to Prefect when configured, falling back to in-process task."""

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
        try:
            from prefect.deployments import run_deployment

            await run_deployment(name=PARSE_DEPLOYMENT, parameters={"job": job.to_prefect_params()}, timeout=0)
            logger.info(
                "statement.parse.submitted_to_prefect",
                statement_id=str(job.statement_id),
                deployment=PARSE_DEPLOYMENT,
                request_id=job.request_id,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "statement.parse.prefect_unavailable_fallback_in_process",
                statement_id=str(job.statement_id),
                error=str(exc),
                request_id=job.request_id,
            )
    return _run_in_process()
