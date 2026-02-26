"""Statement extraction API router."""

import asyncio
import hashlib
import mimetypes
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from src.config import settings
from src.constants.error_ids import ErrorIds
from src.database import create_session_maker_from_db
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import BankStatement, BankStatementStatus, BankStatementTransaction
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.schemas import (
    BankStatementListResponse,
    BankStatementResponse,
    BankStatementTransactionListResponse,
    BankStatementTransactionResponse,
    RetryParsingRequest,
    StatementDecisionRequest,
)
from src.schemas.review import (
    BalanceValidationResult,
    EditAndApproveRequest,
    SetOpeningBalanceRequest,
    StatementReviewResponse,
)
from src.services import ExtractionError, ExtractionService, StorageError, StorageService
from src.services.consistency_checks import (
    get_pending_checks,
    has_unresolved_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.services.openrouter_models import ModelCatalogError, get_model_info, model_matches_modality
from src.services.statement_validation import (
    approve_statement as approve_statement_svc,
    edit_and_approve,
    reject_statement as reject_statement_svc,
    set_opening_balance,
    validate_balance_chain,
)
from src.utils import (
    raise_bad_request,
    raise_internal_error,
    raise_not_found,
    raise_service_unavailable,
    raise_too_large,
)

router = APIRouter(prefix="/statements", tags=["statements"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
logger = get_logger(__name__)

# Track background parsing tasks to avoid garbage collection
_PENDING_PARSE_TASKS: set[asyncio.Task[None]] = set()


def _track_task(task: asyncio.Task[None]) -> None:
    _PENDING_PARSE_TASKS.add(task)
    task.add_done_callback(_PENDING_PARSE_TASKS.discard)


# --- Schemas for Two-Stage Review ---


class ConsistencyCheckResponse(BaseModel):
    id: UUID
    check_type: CheckType
    status: CheckStatus
    related_txn_ids: list[str]
    details: dict
    severity: str
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConsistencyCheckListResponse(BaseModel):
    items: list[ConsistencyCheckResponse]
    total: int


class ResolveCheckRequest(BaseModel):
    action: str = Field(..., description="approve, reject, or flag")
    note: str | None = None


class BatchApproveRequest(BaseModel):
    match_ids: list[UUID] = Field(default_factory=list)


class BatchRejectRequest(BaseModel):
    match_ids: list[UUID] = Field(default_factory=list)


class Stage2ReviewQueueResponse(BaseModel):
    pending_matches: list[dict]
    consistency_checks: list[ConsistencyCheckResponse]
    has_unresolved_checks: bool


# --- Helper functions ---


async def _handle_parse_failure(
    statement: BankStatement,
    db: AsyncSession,
    *,
    message: str | None,
) -> None:
    statement_id = statement.id
    try:
        await db.rollback()
    except Exception as rollback_exc:
        logger.warning(
            "Rollback failed during parse failure handling",
            statement_id=str(statement_id),
            rollback_error=str(rollback_exc),
        )
    try:
        refreshed = await db.get(BankStatement, statement_id)
        if refreshed is None:
            logger.error(
                "Statement not found after rollback",
                statement_id=str(statement_id),
                reason=message,
            )
            return
        refreshed.status = BankStatementStatus.REJECTED
        refreshed.validation_error = message[:500] if message else message
        refreshed.confidence_score = 0
        refreshed.balance_validated = False
        await db.commit()
        logger.error("Statement parsing failed", statement_id=str(refreshed.id), reason=message)
    except Exception as inner_exc:
        logger.exception(
            "Failed to mark statement as rejected",
            statement_id=str(statement_id),
            original_error=message,
            inner_error=str(inner_exc),
        )


async def _parse_statement_background(
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
    session_maker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> None:
    # Bind request_id to context for this background task
    structlog.contextvars.bind_contextvars(
        request_id=request_id, statement_id=str(statement_id), task="parse_statement"
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

        async def update_progress(progress: int) -> None:
            statement.parsing_progress = progress
            await session.commit()

        await update_progress(5)

        storage = StorageService()
        file_url = None
        try:
            file_url = await run_in_threadpool(storage.generate_presigned_url, key=storage_key, public=True)
        except StorageError as exc:
            logger.warning(
                "Could not generate public presigned URL",
                error=str(exc),
                statement_id=str(statement_id),
            )

        await update_progress(10)

        file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
        if file_type == "pdf" and not file_url:
            logger.info(
                "No public URL available for PDF; will use base64-encoded content",
                statement_id=str(statement_id),
            )

        service = ExtractionService()
        try:
            await update_progress(20)
            parsed_statement, transactions = await service.parse_document(
                file_path=Path(filename),
                institution=institution,
                user_id=user_id,
                file_type=file_type,
                account_id=account_id,
                file_content=content,
                file_hash=file_hash,
                file_url=file_url,
                original_filename=filename,
                force_model=model,
                db=session,
            )
            logger.info(
                "Background task enqueued for statement parsing",
                statement_id=str(statement_id),
                model_to_use=model,
                will_use_force_model=bool(model),
                file_type=file_type,
            )
            await update_progress(70)
        except ExtractionError as exc:
            await _handle_parse_failure(statement, session, message=str(exc))
            return
        except Exception as exc:
            logger.exception("Background parsing failed unexpectedly")
            await _handle_parse_failure(statement, session, message=f"Parsing failed: {exc}")
            return

        try:
            statement.institution = parsed_statement.institution
            statement.account_last4 = parsed_statement.account_last4
            statement.currency = parsed_statement.currency
            statement.period_start = parsed_statement.period_start
            statement.period_end = parsed_statement.period_end
            statement.opening_balance = parsed_statement.opening_balance
            statement.closing_balance = parsed_statement.closing_balance
            await session.commit()

            await update_progress(80)

            for existing_tx in list(statement.transactions):
                await session.delete(existing_tx)
            await session.flush()

            if settings.enable_layer_0_write:
                for txn in transactions:
                    txn.statement = statement
                statement.transactions = list(transactions)

            await update_progress(90)

            statement.confidence_score = parsed_statement.confidence_score
            statement.balance_validated = parsed_statement.balance_validated
            statement.validation_error = parsed_statement.validation_error
            statement.status = parsed_statement.status

            await update_progress(100)
            duration = time.perf_counter() - start_time
            logger.info(
                "Background parsing completed",
                duration_ms=round(duration * 1000, 2),
                transactions_count=len(transactions),
            )
        except Exception as exc:
            logger.exception("Failed to finalize statement parsing")
            await _handle_parse_failure(statement, session, message=f"Finalize failed: {exc}")


@router.post("/upload", response_model=BankStatementResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_statement(
    file: UploadFile = File(...),
    institution: Annotated[str | None, Form()] = None,
    account_id: Annotated[UUID | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> BankStatementResponse:
    """
    Upload a financial statement and enqueue parsing.

    Supported file types: PDF, CSV, PNG, JPG. Model is required for PDF/image uploads.
    Institution is optional - AI will auto-detect from document if not provided.
    """
    filename = Path(file.filename or "unknown").name or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"

    logger.info(
        "Statement upload request received",
        user_id=str(user_id),
        filename=filename,
        file_type=extension,
        institution=institution or "(auto-detect)",
        model_requested=model,
        has_account_id=account_id is not None,
    )

    if extension not in ("pdf", "csv", "png", "jpg", "jpeg"):
        raise_bad_request(f"Unsupported file type: {extension}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise_too_large("File exceeds 10MB limit")

    file_hash = hashlib.sha256(content).hexdigest()
    duplicate = await db.execute(
        select(BankStatement.id).where(BankStatement.user_id == user_id).where(BankStatement.file_hash == file_hash)
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate statement upload")

    if extension != "csv":
        if not model:
            raise_bad_request("AI model is required for PDF/image uploads.")

        try:
            model_info = await get_model_info(model)
        except ModelCatalogError as exc:
            raise_service_unavailable("Model catalog unavailable. Please try again.", cause=exc)
        if not model_info:
            raise_bad_request("Invalid model selection. Choose a model from /ai/models.")
        if not model_matches_modality(model_info, "image"):
            raise_bad_request("Selected model does not support image/PDF inputs.")

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
        raise_service_unavailable(str(exc), cause=exc)

    statement = BankStatement(
        id=statement_id,
        user_id=user_id,
        account_id=account_id,
        file_path=storage_key,
        file_hash=file_hash,
        original_filename=filename,
        institution=institution or "Pending Detection",
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
        except StorageError as store_exc:
            logger.error(
                "Failed to clean up storage object after DB error",
                error=str(store_exc),
                error_id=ErrorIds.STORAGE_DELETE_FAILED,
            )
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
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/retry", response_model=BankStatementResponse)
async def retry_statement_parsing(
    statement_id: UUID,
    request: RetryParsingRequest | None = None,
    db: DbSession = None,
    user_id: CurrentUserId = None,
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
        raise_bad_request("Can only retry parsing for parsed, rejected, or stuck parsing statements")

    selected_model = model_override or settings.primary_model

    if model_override:
        try:
            model_info = await get_model_info(model_override)
        except ModelCatalogError as exc:
            raise_service_unavailable("Model catalog unavailable. Please try again.", cause=exc)
        if not model_info:
            raise_bad_request("Invalid model selection. Choose a model from /ai/models.")
        if not model_matches_modality(model_info, "image"):
            raise_bad_request("Selected model does not support image/PDF inputs.")

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
        raise_service_unavailable(f"Failed to fetch file from storage: {exc}", cause=exc)

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
        select(BankStatement).where(BankStatement.id == statement.id).options(selectinload(BankStatement.transactions))
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
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
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
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
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
        select(BankStatement).where(BankStatement.id == statement_id).where(BankStatement.user_id == user_id)
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    # Delete from storage
    if statement.file_path:
        storage = StorageService()
        try:
            await run_in_threadpool(storage.delete_object, statement.file_path)
        except StorageError as exc:
            logger.error(
                "Failed to delete file from storage",
                error=str(exc),
                error_id=ErrorIds.STORAGE_DELETE_FAILED,
                file_path=statement.file_path,
            )
            # Proceed to delete from DB to avoid zombie record

    await db.delete(statement)
    await db.commit()


# --- Two-Stage Review Endpoints ---


@router.get("/{statement_id}/review", response_model=StatementReviewResponse)
async def get_statement_for_review(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> StatementReviewResponse:
    """Get Stage 1 review data for a statement."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    pdf_url = None
    try:
        storage = StorageService()
        pdf_url = await asyncio.to_thread(storage.generate_presigned_url, key=statement.file_path, expires_in=3600)
    except StorageError as exc:
        logger.warning(
            "Could not generate presigned URL for review",
            error=str(exc),
            statement_id=str(statement_id),
        )

    validation_result = await validate_balance_chain(db, statement_id)

    response_data = {
        **{c.name: getattr(statement, c.name) for c in statement.__table__.columns},
        "transactions": statement.transactions,
        "pdf_url": pdf_url,
        "balance_validation_result": BalanceValidationResult(
            opening_balance=validation_result["opening_balance"],
            closing_balance=validation_result["closing_balance"],
            calculated_closing=validation_result["calculated_closing"],
            opening_delta=validation_result["opening_delta"],
            closing_delta=validation_result["closing_delta"],
            opening_match=validation_result["opening_match"],
            closing_match=validation_result["closing_match"],
            validated_at=validation_result["validated_at"],
        ),
    }
    return StatementReviewResponse.model_validate(response_data)


@router.post("/{statement_id}/review/approve", response_model=BankStatementResponse)
async def approve_statement_stage1(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Stage 1: Approve statement with balance validation."""
    try:
        await approve_statement_svc(db, statement_id, user_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/review/reject", response_model=BankStatementResponse)
async def reject_statement_stage1(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Stage 1: Reject statement."""
    try:
        await reject_statement_svc(db, statement_id, user_id, reason=decision.notes)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/review/edit", response_model=BankStatementResponse)
async def edit_and_approve_statement(
    statement_id: UUID,
    request: EditAndApproveRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Stage 1: Edit transactions and approve."""
    edits_data = [{**e.model_dump(), "txn_id": str(e.txn_id)} for e in request.edits]
    try:
        await edit_and_approve(db, statement_id, user_id, edits_data)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/review/opening-balance", response_model=BankStatementResponse)
async def set_statement_opening_balance(
    statement_id: UUID,
    request: SetOpeningBalanceRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Set manual opening balance override."""
    try:
        await set_opening_balance(db, statement_id, user_id, request.opening_balance)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.get("/stage2/queue", response_model=Stage2ReviewQueueResponse)
async def get_stage2_review_queue(
    db: DbSession,
    user_id: CurrentUserId,
) -> Stage2ReviewQueueResponse:
    """Stage 2: Get review queue (matches + checks)."""
    matches_result = await db.execute(
        select(ReconciliationMatch)
        .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
        .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
        .where(
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            BankStatement.user_id == user_id,
        )
        .limit(50)
    )
    pending_matches = []
    for match in matches_result.scalars().all():
        pending_matches.append(
            {
                "id": str(match.id),
                "match_score": match.match_score,
                "status": match.status.value,
                "created_at": match.created_at.isoformat() if match.created_at else None,
            }
        )

    checks = await get_pending_checks(db, user_id)

    return Stage2ReviewQueueResponse(
        pending_matches=pending_matches,
        consistency_checks=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        has_unresolved_checks=await has_unresolved_checks(db, user_id),
    )


@router.post("/{statement_id}/stage2/run-checks", response_model=ConsistencyCheckListResponse)
async def run_stage2_checks(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ConsistencyCheckListResponse:
    """Run consistency checks for a statement."""
    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).where(BankStatement.user_id == user_id)
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise_not_found("Statement")

    checks = await run_all_consistency_checks(db, user_id, statement_id)
    await db.commit()

    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=len(checks),
    )


@router.post("/consistency-checks/{check_id}/resolve", response_model=ConsistencyCheckResponse)
async def resolve_consistency_check(
    check_id: UUID,
    request: ResolveCheckRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ConsistencyCheckResponse:
    """Resolve a consistency check."""
    try:
        check = await resolve_check(db, check_id, request.action, user_id, request.note)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ConsistencyCheckResponse.model_validate(check)


@router.get("/consistency-checks/list", response_model=ConsistencyCheckListResponse)
async def list_consistency_checks(
    db: DbSession,
    user_id: CurrentUserId,
    status: CheckStatus | None = None,
    check_type: CheckType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ConsistencyCheckListResponse:
    """List/filter consistency checks."""
    query = (
        select(ConsistencyCheck)
        .where(ConsistencyCheck.user_id == user_id)
        .order_by(ConsistencyCheck.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    count_query = select(func.count()).select_from(ConsistencyCheck).where(ConsistencyCheck.user_id == user_id)

    if status:
        query = query.where(ConsistencyCheck.status == status)
        count_query = count_query.where(ConsistencyCheck.status == status)
    if check_type:
        query = query.where(ConsistencyCheck.check_type == check_type)
        count_query = count_query.where(ConsistencyCheck.check_type == check_type)

    result = await db.execute(query)
    checks = list(result.scalars().all())

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=total,
    )


@router.post("/batch-approve-matches", response_model=dict)
async def batch_approve_matches(
    request: BatchApproveRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> dict:
    """Batch approve matches (blocked by unresolved checks)."""
    if await has_unresolved_checks(db, user_id):
        return {
            "success": False,
            "error": "Cannot batch approve while there are unresolved consistency checks",
            "approved_count": 0,
        }

    if not request.match_ids:
        return {"success": True, "approved_count": 0}

    result = await db.execute(
        select(ReconciliationMatch)
        .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
        .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
        .where(
            ReconciliationMatch.id.in_(request.match_ids),
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            BankStatement.user_id == user_id,
        )
    )
    matches = list(result.scalars().all())

    approved_count = 0
    for match in matches:
        match.status = ReconciliationStatus.ACCEPTED
        match.version += 1
        approved_count += 1

    await db.commit()

    return {
        "success": True,
        "approved_count": approved_count,
    }


@router.post("/batch-reject-matches", response_model=dict)
async def batch_reject_matches(
    request: BatchRejectRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> dict:
    """Batch reject matches."""
    if not request.match_ids:
        return {"success": True, "rejected_count": 0}

    result = await db.execute(
        select(ReconciliationMatch)
        .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
        .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
        .where(
            ReconciliationMatch.id.in_(request.match_ids),
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            BankStatement.user_id == user_id,
        )
    )
    matches = list(result.scalars().all())

    rejected_count = 0
    for match in matches:
        match.status = ReconciliationStatus.REJECTED
        match.version += 1
        rejected_count += 1

    await db.commit()

    return {
        "success": True,
        "rejected_count": rejected_count,
    }


async def wait_for_parse_tasks() -> None:
    """Wait for all pending background parsing tasks to complete. Useful for tests."""
    if _PENDING_PARSE_TASKS:
        await asyncio.gather(*_PENDING_PARSE_TASKS, return_exceptions=True)
