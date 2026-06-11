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

``prefect`` is imported lazily here, so the fallback path never needs it. Any
process that runs with ``PREFECT_API_URL`` set must install the ``prefect`` extra
— both the API (to *submit* the run) and the worker (to *execute* it). The base
image / CI / fallback do not.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import create_session_maker_from_db
from src.logger import get_logger
from src.services.statement_parsing import parse_statement_background

logger = get_logger(__name__)

# Prefect deployment name "<flow-name>/<deployment-name>".
PARSE_DEPLOYMENT = "parse-statement/parse-statement"


async def submit_parse_pipeline(
    *,
    statement_id: UUID,
    filename: str,
    institution: str | None,
    user_id: UUID,
    account_id: UUID | None,
    file_hash: str,
    storage_key: str,
    content: bytes,
    model: str | None,
    db: AsyncSession,
    request_id: str | None,
) -> asyncio.Task[None] | None:
    """Dispatch statement parsing.

    Returns the in-process ``asyncio.Task`` for the caller to track in fallback
    mode, or ``None`` when the work was submitted to Prefect.

    Note: in Prefect mode ``content`` is not sent to the worker (it re-fetches
    from ``storage_key``). Avoiding the caller's pre-download in that mode is a
    P1 optimization deferred until the worker lands; in P0 (fallback only) the
    content is needed in-process anyway.
    """
    if settings.prefect_api_url:
        # Remote durable execution. Only serializable params cross the boundary
        # (no raw bytes, no session maker): the worker re-fetches ``content``
        # from storage and builds its own DB session.
        from prefect.deployments import run_deployment  # lazy: fallback never imports prefect

        await run_deployment(
            name=PARSE_DEPLOYMENT,
            parameters={
                "statement_id": str(statement_id),
                "filename": filename,
                "institution": institution,
                "user_id": str(user_id),
                "account_id": str(account_id) if account_id is not None else None,
                "file_hash": file_hash,
                "storage_key": storage_key,
                "model": model,
                "request_id": request_id,
            },
            timeout=0,  # fire-and-submit: do not block the upload request on completion
        )
        logger.info(
            "statement.parse.submitted_to_prefect",
            statement_id=str(statement_id),
            deployment=PARSE_DEPLOYMENT,
            request_id=request_id,
        )
        return None

    return asyncio.create_task(
        parse_statement_background(
            statement_id=statement_id,
            filename=filename,
            institution=institution,
            user_id=user_id,
            account_id=account_id,
            file_hash=file_hash,
            storage_key=storage_key,
            content=content,
            model=model,
            session_maker=create_session_maker_from_db(db),
            request_id=request_id,
        )
    )
