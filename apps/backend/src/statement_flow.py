"""Prefect flow for durable statement parsing (EPIC-019).

This L4 worker entrypoint imports ``prefect`` at load time, so it is imported ONLY
by the Prefect worker (which runs this same backend image, per the
promote-not-rebuild release model) and by ``scripts/register_prefect_deployment.py``
— never by the API process in fallback mode. The config-gated dispatch lives in
``src.extraction.extension.statement_pipeline``.
"""

from __future__ import annotations

from collections.abc import Callable

from prefect import flow

from src.composition import compose_statement_ingestion_use_case
from src.database import async_session_maker
from src.extraction import ParseJob, StatementIngestionUseCase
from src.observability import flow_run_telemetry, get_logger, run_with_async_parse_tracking

logger = get_logger(__name__)


@flow(name="parse-statement")
async def parse_statement_flow(
    *,
    job: dict[str, str | None],
    use_case_factory: Callable[..., StatementIngestionUseCase] | None = None,
) -> None:
    """Durable statement parse of one run.

    Re-fetches content from storage and uses the worker's own session maker, then runs the use case.
    The flow has no retries: the use case retries a retryable error as a new system run (#2994).
    """
    with flow_run_telemetry():
        parse_job = ParseJob.from_prefect_params(job)
        logger.info(
            "statement.parse.flow_started",
            statement_id=str(parse_job.statement_id),
            request_id=parse_job.request_id,
        )
        factory = use_case_factory or compose_statement_ingestion_use_case
        use_case = factory(session_maker=async_session_maker)
        await run_with_async_parse_tracking(
            use_case.execute(parse_job),
            statement_id=parse_job.statement_id,
            request_id=parse_job.request_id,
        )
