"""Prefect flows for durable parsing, classification, and scheduled maintenance on pool ``finance-report``.

This L4 worker entrypoint imports ``prefect`` at load time, so it is imported ONLY
by the Prefect worker (which runs this same backend image, per the
promote-not-rebuild release model) and by ``scripts/register_prefect_deployment.py``
— never by the API process in fallback mode. The config-gated dispatch lives in
``src.extraction.extension.statement_pipeline``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from uuid import UUID

from prefect import flow

from src.composition import (
    compose_statement_ingestion_use_case,
    compose_statement_posting_dependencies,
    market_data_scopes,
)
from src.config import settings
from src.database import async_session_maker
from src.extraction import (
    ParseJob,
    StatementIngestionUseCase,
    analyze_tenant_tables,
    execute_classify_run,
    get_known_storage_paths,
    reap_stale_parsing_runs,
)
from src.observability import (
    flow_run_telemetry,
    get_logger,
    record_market_data_sync_failure,
    run_with_async_parse_tracking,
)
from src.pricing import run_daily_market_data_sync
from src.runtime import sweep_orphaned_storage_objects

logger = get_logger(__name__)


@flow(name="parse-statement", retries=0)
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


@flow(name="classify-statement", retries=0)
async def classify_statement_flow(*, run_id: str) -> int:
    """Durable transaction classification flow with post-classify PostgreSQL ANALYZE."""
    with flow_run_telemetry():
        posted = await execute_classify_run(
            async_session_maker,
            run_id=UUID(run_id),
            posting_dependencies=compose_statement_posting_dependencies(),
        )
        if settings.environment != "testing" and os.environ.get("ENVIRONMENT") != "testing":
            try:
                async with async_session_maker() as session:
                    bind = session.get_bind()
                    is_pg = bind is not None and bind.dialect.name == "postgresql"
                if is_pg:
                    await analyze_tenant_tables(async_session_maker)
            except Exception as exc:  # noqa: BLE001 - analyze is best-effort after classification commits
                logger.warning("statement.classification.statistics_refresh_failed", error_type=type(exc).__name__)
        return posted


@flow(name="market-data-sync", retries=0)
async def market_data_sync_flow() -> dict[str, int]:
    """Scheduled daily FX and equity market-data sync."""
    with flow_run_telemetry():
        try:
            await run_daily_market_data_sync(market_data_scopes, sessionmaker=async_session_maker)
        except Exception as exc:
            record_market_data_sync_failure(reason=type(exc).__name__)
            raise
        return {"completed": 1}


@flow(name="storage-sweep", retries=0)
async def storage_sweep_flow() -> dict[str, int]:
    """Scheduled daily orphaned S3 object sweep (skips preview environments)."""
    with flow_run_telemetry():
        env_name = (os.environ.get("ENVIRONMENT") or settings.environment or "").strip().lower()
        if env_name.startswith("preview") or env_name in ("pr", "branch"):
            return {"deleted": 0}
        deleted = await sweep_orphaned_storage_objects(known_paths_provider=get_known_storage_paths)
        return {"deleted": deleted}


@flow(name="parsing-supervisor-reap", retries=0)
async def parsing_supervisor_reap_flow() -> dict[str, int]:
    """Periodic stale parsing run reaper."""
    with flow_run_telemetry():
        reaped = await reap_stale_parsing_runs(sessionmaker=async_session_maker)
        return {"reaped": reaped}


@flow(name="staging-db-hygiene", retries=0)
async def staging_db_hygiene_flow(*, older_than_days: int = 14) -> dict[str, int]:
    """Scheduled staging test-account and append-only rotation purge."""
    with flow_run_telemetry():
        from scripts.purge_test_accounts import _parse_args, _run

        args = _parse_args(["--rotate-append-only", "--older-than-days", str(older_than_days), "--apply"])
        exit_code = await _run(args, session_maker=async_session_maker)
        return {"exit_code": exit_code}
