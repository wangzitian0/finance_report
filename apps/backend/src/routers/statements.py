"""Statement extraction API router."""

import asyncio
import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from src.config import settings
from src.database import create_session_maker_from_db
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import BankStatement, BankStatementStatus
from src.schemas import (
    BankStatementListResponse,
    BankStatementResponse,
    BankStatementTransactionListResponse,
    BankStatementTransactionResponse,
    RetryParsingRequest,
    StatementDecisionRequest,
)
from src.services import ExtractionError, ExtractionService, StorageError, StorageService
from src.services.openrouter_models import (
    fetch_model_catalog,
    model_matches_modality,
    normalize_model_entry,
)
from src.utils import raise_bad_request, raise_internal_error, raise_not_found

router = APIRouter(prefix="/statements", tags=["statements"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
logger = get_logger(__name__)

# Track background parsing tasks to avoid garbage collection
_PENDING_PARSE_TASKS: set[asyncio.Task[None]] = set()


def _track_task(task: asyncio.Task[None]) -> None:
    _PENDING_PARSE_TASKS.add(task)
    task.add_done_callback(_PENDING_PARSE_TASKS.discard)


async def _handle_parse_failure(
    statement: BankStatement,
    db: AsyncSession,
    *,
    message: str,
) -> None:
    logger.error("Statement parsing failed", statement_id=statement.id, reason=message)
    statement.status = BankStatementStatus.REJECTED
    statement.validation_error = message
    statement.confidence_score = 0
    statement.balance_validated = False
    await db.commit()


async def _parse_statement_background(
    *,
    statement_id: UUID,
    filename: str,
    institution: str,
    user_id: UUID,
    account_id: UUID | None,
    file_hash: str,
    storage_key: str,
    content: bytes,
    model: str | None,
    session_maker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> None:
    # Bind request_id to context for this background task
    structlog.contextvars.bind_contextvars(
        request_id=request_id, statement_id=statement_id, task="parse_statement"
    )

    logger.info("Starting background parsing", filename=filename)
    start_time = time.perf_counter()

    async with session_maker() as session:
        statement = await session.get(
            BankStatement,
            statement_id,
            options=[selectinload(BankStatement.transactions)],
        )
        if not statement:
            logger.error("Statement not found in DB for background parsing")
            return

        storage = StorageService()
        try:
            # Generate public URL for AI service access
            file_url = await run_in_threadpool(
                storage.generate_presigned_url, key=storage_key, public=True
            )
        except StorageError as exc:
            await _handle_parse_failure(statement, session, message=str(exc))
            return

        service = ExtractionService()
        try:
            parsed_statement, transactions = await service.parse_document(
                file_path=Path(filename),
                institution=institution,
                user_id=user_id,
                file_type=filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf",
                account_id=account_id,
                file_content=content,
                file_hash=file_hash,
                file_url=file_url,
                original_filename=filename,
                force_model=model,
            )
        except ExtractionError as exc:
            await _handle_parse_failure(statement, session, message=str(exc))
            return
        except Exception as exc:
            logger.exception("Background parsing failed unexpectedly")
            await _handle_parse_failure(statement, session, message=f"Parsing failed: {exc}")
            return

        for existing_tx in list(statement.transactions):
            await session.delete(existing_tx)
        await session.flush()

        for txn in transactions:
            txn.statement = statement

        statement.transactions = list(transactions)
        statement.account_last4 = parsed_statement.account_last4
        statement.currency = parsed_statement.currency
        statement.period_start = parsed_statement.period_start
        statement.period_end = parsed_statement.period_end
        statement.opening_balance = parsed_statement.opening_balance
        statement.closing_balance = parsed_statement.closing_balance
        statement.confidence_score = parsed_statement.confidence_score
        statement.balance_validated = parsed_statement.balance_validated
        statement.validation_error = parsed_statement.validation_error
        statement.status = parsed_statement.status

        await session.commit()
        duration = time.perf_counter() - start_time
        logger.info(
            "Background parsing completed",
            duration_ms=round(duration * 1000, 2),
            transactions_count=len(transactions),
        )


@router.post("/upload", response_model=BankStatementResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_statement(
    file: UploadFile = File(...),
    institution: Annotated[str, Form()] = ...,
    account_id: Annotated[UUID | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """
    Upload a financial statement and enqueue parsing.

    Supported file types: PDF, CSV, PNG, JPG. Optional model override via form field.
    """
    filename = Path(file.filename or "unknown").name or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"

    if extension not in ("pdf", "csv", "png", "jpg", "jpeg"):
        raise_bad_request(f"Unsupported file type: {extension}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 10MB limit",
        )

    file_hash = hashlib.sha256(content).hexdigest()
    duplicate = await db.execute(
        select(BankStatement.id)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.file_hash == file_hash)
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate statement upload")

    if model:
        allowed_models = {settings.primary_model} | set(settings.fallback_models)
        if model not in allowed_models:
            try:
                models = await fetch_model_catalog()
                match = next(
                    (normalize_model_entry(m) for m in models if m.get("id") == model),
                    None,
                )
                if not match:
                    raise_bad_request("Invalid model selection.")
                if extension != "csv" and not model_matches_modality(match, "image"):
                    raise_bad_request("Selected model does not support image inputs.")
            except HTTPException:
                raise
            except Exception as e:
                logger.exception("Failed to validate model catalog for model '%s'", model)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to validate the requested model at this time.",
                ) from e

    statement_id = uuid4()
    storage_key = f"statements/{user_id}/{statement_id}/{filename}"

    storage = StorageService()
    try:
        await run_in_threadpool(
            storage.upload_bytes,
            key=storage_key,
            content=content,
            content_type=mimetypes.guess_type(filename)[0] or "application/pdf",
        )
    except StorageError as exc:
        logger.error("Failed to upload statement to storage", error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    statement = BankStatement(
        id=statement_id,
        user_id=user_id,
        account_id=account_id,
        file_path=storage_key,
        file_hash=file_hash,
        original_filename=filename,
        institution=institution,
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
        currency=None,
        period_start=None,
        period_end=None,
        opening_balance=None,
        closing_balance=None,
    )

    db.add(statement)
    try:
        await db.commit()
        await db.refresh(statement)
    except Exception as exc:
        await db.rollback()
        try:
            await run_in_threadpool(storage.delete_object, storage_key)
        except StorageError:
            logger.warning("Failed to clean up storage object after DB error", exc_info=True)
        raise_internal_error("Failed to persist statement metadata", cause=exc)

    task = asyncio.create_task(
        _parse_statement_background(
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
            request_id=structlog.contextvars.get_contextvars().get("request_id"),
        )
    )
    _track_task(task)

    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/retry", response_model=BankStatementResponse)
async def retry_statement_parsing(
    statement_id: UUID,
    request: RetryParsingRequest | None = None,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Retry parsing with a different model (e.g., stronger model for better accuracy)."""
    model_override = request.model if request else None

    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    if statement.status not in (
        BankStatementStatus.PARSED,
        BankStatementStatus.REJECTED,
        BankStatementStatus.PARSING,
    ):
        raise HTTPException(
            400, "Can only retry parsing for parsed, rejected, or stuck parsing statements"
        )

    if not settings.fallback_models:
        raise_internal_error("No fallback models are configured for statement parsing")

    selected_model = model_override or settings.fallback_models[0]
    allowed_models = {settings.primary_model} | set(settings.fallback_models)
    if selected_model not in allowed_models:
        try:
            models = await fetch_model_catalog()
            match = next(
                (normalize_model_entry(m) for m in models if m.get("id") == selected_model),
                None,
            )
            if not match:
                raise_bad_request("Invalid model selection.")
            if not model_matches_modality(match, "image"):
                raise_bad_request("Selected model does not support image inputs.")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Failed to validate model catalog for model '%s'", selected_model)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to validate the requested model at this time.",
            ) from e

    # Reset status to PARSING before starting background task
    statement.status = BankStatementStatus.PARSING
    statement.validation_error = None
    await db.commit()
    await db.refresh(statement)

    # Need file content for some vision models if URL fails or for consistency
    # But retry currently doesn't have the original 'content' bytes in memory.
    # It must fetch from storage or use URL.
    # The _parse_statement_background requires 'content: bytes'.
    # We'll fetch it from storage now.
    try:
        storage = StorageService()
        content = await run_in_threadpool(storage.get_object, statement.file_path)
    except StorageError as exc:
        raise HTTPException(503, f"Failed to fetch file from storage: {exc}")

    task = asyncio.create_task(
        _parse_statement_background(
            statement_id=statement.id,
            filename=statement.original_filename,
            institution=statement.institution,
            user_id=user_id,
            account_id=statement.account_id,
            file_hash=statement.file_hash,
            storage_key=statement.file_path,
            content=content,
            model=selected_model,
            session_maker=create_session_maker_from_db(db),
            request_id=structlog.contextvars.get_contextvars().get("request_id"),
        )
    )
    _track_task(task)

    # Re-fetch statement with transactions to avoid MissingGreenlet error during Pydantic validation
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement.id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()

    return BankStatementResponse.model_validate(statement)


@router.get("", response_model=BankStatementListResponse)
async def list_statements(
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementListResponse:
    """List all statements for the current user."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
        .order_by(BankStatement.created_at.desc())
    )
    statements = result.scalars().all()

    total_result = await db.execute(
        select(func.count()).select_from(BankStatement).where(BankStatement.user_id == user_id)
    )
    total = total_result.scalar() or 0

    return BankStatementListResponse(
        items=[BankStatementResponse.model_validate(s) for s in statements],
        total=total,
    )


@router.get("/pending-review", response_model=BankStatementListResponse)
async def list_pending_review(
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementListResponse:
    """List statements pending human review (confidence 60-84)."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.PARSED)
        .where(BankStatement.confidence_score >= 60)
        .where(BankStatement.confidence_score < 85)
        .options(selectinload(BankStatement.transactions))
        .order_by(BankStatement.created_at.desc())
    )
    statements = result.scalars().all()

    total_result = await db.execute(
        select(func.count())
        .select_from(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.PARSED)
        .where(BankStatement.confidence_score >= 60)
        .where(BankStatement.confidence_score < 85)
    )
    total = total_result.scalar() or 0

    return BankStatementListResponse(
        items=[BankStatementResponse.model_validate(s) for s in statements],
        total=total,
    )


@router.get("/{statement_id}", response_model=BankStatementResponse)
async def get_statement(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Get a statement with all its transactions."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    return BankStatementResponse.model_validate(statement)


@router.get("/{statement_id}/transactions", response_model=BankStatementTransactionListResponse)
async def list_statement_transactions(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementTransactionListResponse:
    """List transactions for a statement."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    items = [BankStatementTransactionResponse.model_validate(t) for t in statement.transactions]
    return BankStatementTransactionListResponse(items=items, total=len(items))


@router.post("/{statement_id}/approve", response_model=BankStatementResponse)
async def approve_statement(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Approve a statement after human review."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    statement.status = BankStatementStatus.APPROVED
    if decision.notes:
        statement.validation_error = decision.notes

    await db.commit()

    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/reject", response_model=BankStatementResponse)
async def reject_statement(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Reject a statement after human review."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    statement.status = BankStatementStatus.REJECTED
    if decision.notes:
        statement.validation_error = decision.notes

    await db.commit()

    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.delete("/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_statement(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a statement."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    # Delete from storage
    if statement.file_path:
        storage = StorageService()
        try:
            await run_in_threadpool(storage.delete_object, statement.file_path)
        except StorageError:
            logger.warning("Failed to delete file from storage", exc_info=True)
            # Proceed to delete from DB to avoid zombie record

    await db.delete(statement)
    await db.commit()


async def wait_for_parse_tasks() -> None:
    """Wait for all pending background parsing tasks to complete. Useful for tests."""
    if _PENDING_PARSE_TASKS:
        await asyncio.gather(*_PENDING_PARSE_TASKS, return_exceptions=True)
