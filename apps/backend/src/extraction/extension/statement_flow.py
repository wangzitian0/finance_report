"""Prefect flow for durable statement parsing (EPIC-019).

This module imports ``prefect`` at load time, so it is imported ONLY by the
Prefect worker (which runs this same backend image, per the
promote-not-rebuild release model) and by ``scripts/register_prefect_deployment.py``
— never by the API process in fallback mode. The config-gated dispatch lives
in ``statement_pipeline.py``.
"""

from __future__ import annotations

from prefect import flow

from src.database import async_session_maker
from src.extraction.base.types import ParseJob
from src.observability import get_logger, run_with_async_parse_tracking

logger = get_logger(__name__)


def compose_statement_ingestion_use_case(*, session_maker):
    """Lazy composition import keeps worker startup independent from src.main."""
    from src.composition import compose_statement_ingestion_use_case as compose

    return compose(session_maker=session_maker)


@flow(name="parse-statement", retries=2, retry_delay_seconds=30)
async def parse_statement_flow(
    *,
    job: dict[str, str | None],
) -> None:
    """Durable, retriable statement parse.

    Re-fetches content from storage and uses the worker's own session maker,
    then runs the existing parse logic. Idempotency is keyed on ``statement_id``
    (the underlying parse persists by statement id), so retries/re-runs are safe.
    """
    parse_job = ParseJob.from_prefect_params(job)
    logger.info(
        "statement.parse.flow_started",
        statement_id=str(parse_job.statement_id),
        request_id=parse_job.request_id,
    )
    use_case = compose_statement_ingestion_use_case(session_maker=async_session_maker)
    await run_with_async_parse_tracking(
        use_case.execute(parse_job),
        statement_id=parse_job.statement_id,
        request_id=parse_job.request_id,
    )
