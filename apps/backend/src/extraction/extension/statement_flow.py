"""Prefect flow for durable statement parsing (EPIC-019).

This module imports ``prefect`` at load time, so it is imported ONLY by the
Prefect worker (which runs this same backend image, per the
promote-not-rebuild release model) and by ``scripts/register_prefect_deployment.py``
— never by the API process in fallback mode. The config-gated dispatch lives
in ``statement_pipeline.py``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from prefect import flow

from src.database import async_session_maker
from src.extraction.extension.statement_parsing import parse_statement_background
from src.observability import get_logger, run_with_async_parse_tracking
from src.runtime import StorageService

logger = get_logger(__name__)


@flow(name="parse-statement", retries=2, retry_delay_seconds=30)
async def parse_statement_flow(
    *,
    statement_id: str,
    filename: str,
    institution: str | None,
    user_id: str,
    account_id: str | None,
    file_hash: str,
    storage_key: str,
    model: str | None,
    request_id: str | None = None,
) -> None:
    """Durable, retriable statement parse.

    Re-fetches content from storage and uses the worker's own session maker,
    then runs the existing parse logic. Idempotency is keyed on ``statement_id``
    (the underlying parse persists by statement id), so retries/re-runs are safe.
    """
    logger.info(
        "statement.parse.flow_started",
        statement_id=statement_id,
        request_id=request_id,
    )
    storage = StorageService()
    content = await run_in_threadpool(storage.get_object, storage_key)
    await run_with_async_parse_tracking(
        parse_statement_background(
            statement_id=UUID(statement_id),
            filename=filename,
            institution=institution,
            user_id=UUID(user_id),
            account_id=UUID(account_id) if account_id else None,
            file_hash=file_hash,
            storage_key=storage_key,
            content=content,
            model=model,
            session_maker=async_session_maker,
            request_id=request_id,
        ),
        statement_id=statement_id,
        request_id=request_id,
    )
