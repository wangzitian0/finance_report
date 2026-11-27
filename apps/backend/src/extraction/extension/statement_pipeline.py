"""Config-gated dispatch for the upload-to-report async pipeline (EPIC-019)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.config
from src.extraction.base.types import ParseJob
from src.extraction.extension.statement_classification_run import execute_classify_run
from src.extraction.extension.statement_parsing import StatementIngestionUseCase
from src.extraction.extension.statement_posting import StatementPostingDependencies
from src.extraction.extension.uploaded_document_reads import resolve_uploaded_document  # noqa: F401
from src.observability import get_logger, run_with_async_parse_tracking

logger = get_logger(__name__)
settings = src.config.settings

PARSE_DEPLOYMENT = "parse-statement/parse-statement"
CLASSIFY_DEPLOYMENT = "classify-statement/classify-statement"
PENDING_PARSE_TASKS: set[asyncio.Task] = set()


def track_parse_task(task: asyncio.Task) -> None:
    """Register an in-flight background statement parse or classify task."""
    PENDING_PARSE_TASKS.add(task)
    task.add_done_callback(PENDING_PARSE_TASKS.discard)


async def wait_for_parse_tasks() -> None:
    """Wait for all pending background statement parse or classify tasks."""
    if PENDING_PARSE_TASKS:
        await asyncio.gather(*PENDING_PARSE_TASKS, return_exceptions=True)


def _consume_background_task_exception(task: asyncio.Task) -> None:
    with suppress(asyncio.CancelledError):
        task.exception()


async def submit_classify_run(
    run_id: UUID,
    *,
    session_maker: async_sessionmaker[AsyncSession],
    posting_dependencies: StatementPostingDependencies,
) -> asyncio.Task[int] | None:
    """Dispatch classification to Prefect when configured; fail closed on Prefect error; run in-process only when unset."""
    if settings.prefect_api_url:
        from prefect.deployments import run_deployment

        await run_deployment(name=CLASSIFY_DEPLOYMENT, parameters={"run_id": str(run_id)}, timeout=0)
        logger.info("statement.classification.submitted_to_prefect", run_id=str(run_id), deployment=CLASSIFY_DEPLOYMENT)
        return None
    task = asyncio.create_task(
        execute_classify_run(
            session_maker,
            run_id=run_id,
            posting_dependencies=posting_dependencies,
        )
    )
    task.add_done_callback(_consume_background_task_exception)
    return task


async def submit_parse_pipeline(
    *,
    job: ParseJob,
    content: bytes,
    use_case_factory: Callable[[], StatementIngestionUseCase],
) -> asyncio.Task[None] | None:
    """Dispatch statement parsing to Prefect when configured; fail closed if PREFECT_API_URL is set."""

    def _run_in_process() -> asyncio.Task[None]:
        use_case = use_case_factory()
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
        import time

        from prefect.deployments import run_deployment

        dispatch_started = time.perf_counter()
        try:
            await run_deployment(name=PARSE_DEPLOYMENT, parameters={"job": job.to_prefect_params()}, timeout=0)
        except Exception as exc:
            logger.error(
                "statement.parse.prefect_dispatch_failed",
                statement_id=str(job.statement_id),
                error=str(exc),
                request_id=job.request_id,
            )
            raise
        logger.info(
            "statement.parse.submitted_to_prefect",
            statement_id=str(job.statement_id),
            deployment=PARSE_DEPLOYMENT,
            request_id=job.request_id,
            prefect_submit_ms=round((time.perf_counter() - dispatch_started) * 1000, 2),
        )
        return None
    return _run_in_process()
