"""Statement extraction API router."""

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.constants.error_ids import ErrorIds
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    BankStatementStatus,
    UploadedDocument,
)
from src.models.layer2 import AtomicTransaction
from src.models.statement_summary import StatementSummary
from src.schemas import (
    AtomicTransactionResponse,
    BankStatementListResponse,
    BankStatementResponse,
    BankStatementTransactionListResponse,
    RetryParsingRequest,
    StatementDecisionRequest,
)
from src.schemas.extraction import compose_statement_response
from src.schemas.portfolio import BrokerageImportResponse
from src.schemas.review import (
    BalanceValidationResult,
    EditAndApproveRequest,
    SetOpeningBalanceRequest,
    Stage1ApprovalRequest,
    Stage1ApprovalResponse,
    StatementReviewResponse,
)
from src.services import StorageError, StorageService
from src.services.ai_models import ModelCatalogError, get_model_info, model_matches_modality
from src.services.brokerage_positions import BrokeragePositionImportService
from src.services.statement_pipeline import submit_parse_pipeline
from src.services.statement_posting import auto_create_posted_entries_for_statement, resolve_statement_posting_account
from src.services.statement_validation import (
    approve_statement as approve_statement_svc,
    edit_and_approve,
    pending_stage1_review_filter,
    reject_statement as reject_statement_svc,
    resolve_statement_transactions,
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
_BROKERAGE_IMPORT_SERVICE = BrokeragePositionImportService()


def _track_task(task: asyncio.Task[None]) -> None:
    _PENDING_PARSE_TASKS.add(task)
    task.add_done_callback(_PENDING_PARSE_TASKS.discard)


def _current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    if value:
        return str(value)
    generated = str(uuid4())
    structlog.contextvars.bind_contextvars(request_id=generated)
    return generated


def _safe_error_message(message: str | None) -> str | None:
    return message[:500] if message else message


async def _resolve_uploaded_document(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
) -> UploadedDocument | None:
    """Resolve the ODS ``UploadedDocument`` backing a statement envelope.

    The canonical join is ``StatementSummary.uploaded_document_id``; fall back to the
    shared ``(user_id, file_hash)`` key so file ops still resolve before the document
    link has been written by the ingestion pipeline.
    """
    if statement.uploaded_document_id is not None:
        document = await db.get(UploadedDocument, statement.uploaded_document_id)
        if document is not None:
            return document

    result = await db.execute(
        select(UploadedDocument)
        .where(UploadedDocument.user_id == user_id)
        .where(UploadedDocument.file_hash == statement.file_hash)
    )
    return result.scalar_one_or_none()


async def _compose_statement_response(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
) -> BankStatementResponse:
    """Build a ``BankStatementResponse`` from the DWD records for a statement."""
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    transactions = await resolve_statement_transactions(db, statement)
    return compose_statement_response(statement, uploaded_document, transactions)


async def _get_statement_or_404(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> StatementSummary:
    result = await db.execute(
        select(StatementSummary).where(StatementSummary.id == statement_id).where(StatementSummary.user_id == user_id)
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise_not_found("Statement")
    return statement


async def _queue_statement_reparse(
    db: DbSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    model: str | None = None,
) -> None:
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    if uploaded_document is None:
        raise StorageError("Source document is no longer available for reparse")
    storage_key = uploaded_document.file_path
    filename = uploaded_document.original_filename

    storage = StorageService()
    content = await run_in_threadpool(storage.get_object, storage_key)
    request_id = _current_request_id()
    model_to_use = None if model == settings.ocr_model else model
    task = await submit_parse_pipeline(
        statement_id=statement.id,
        filename=filename,
        institution=statement.institution,
        user_id=user_id,
        account_id=statement.account_id,
        file_hash=statement.file_hash,
        storage_key=storage_key,
        content=content,
        model=model_to_use,
        db=db,
        request_id=request_id,
    )
    if task is not None:
        _track_task(task)
    logger.info(
        "statement.parse.enqueued",
        audit_event="statement.parse.enqueued",
        request_id=request_id,
        statement_id=str(statement.id),
        filename=filename,
        file_type=filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf",
        model_to_use=model_to_use,
    )


async def _create_statement_account_from_confirmation(
    db: DbSession,
    statement: StatementSummary,
    user_id: UUID,
) -> Account:
    """Create and bind a statement account after explicit Stage 1 user confirmation."""
    if statement.account_id:
        account_result = await db.execute(
            select(Account).where(Account.id == statement.account_id).where(Account.user_id == user_id)
        )
        account = account_result.scalar_one_or_none()
        if account:
            return account
        raise ValueError("Statement account mapping is invalid. Confirm the target account before posting.")

    currency = (statement.currency or "SGD").strip().upper()
    institution = (statement.institution or "").strip()
    account_name = institution or "Statement Account"
    if statement.account_last4:
        account_name = f"{account_name} *{statement.account_last4.strip()}"

    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    source_filename = uploaded_document.original_filename if uploaded_document else statement.file_hash

    account = Account(
        user_id=user_id,
        name=account_name,
        type=AccountType.ASSET,
        currency=currency,
        description=f"Created from confirmed statement import {source_filename}",
    )
    db.add(account)
    await db.flush()
    statement.account_id = account.id
    await db.flush()
    return account


# --- Helper functions ---


def build_statement_storage_key(*, statement_id: UUID, file_hash: str, extension: str) -> str:
    """Build a non-PII object key for uploaded statement content."""
    safe_extension = extension.lower() if extension.lower() in {"pdf", "csv", "png", "jpg", "jpeg"} else "bin"
    return f"statements/{statement_id}/{file_hash[:16]}.{safe_extension}"


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

    Supported file types: PDF, CSV, PNG, JPG. Model is optional for PDF/image uploads;
    omitted model uses the OCR-first default pipeline.
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

    if account_id is not None:
        account_result = await db.execute(
            select(Account.id).where(Account.id == account_id).where(Account.user_id == user_id)
        )
        if account_result.scalar_one_or_none() is None:
            raise_not_found("Account")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise_too_large("File exceeds 10MB limit")

    file_hash = hashlib.sha256(content).hexdigest()
    file_hash_prefix = file_hash[:12]
    duplicate = await db.execute(
        select(StatementSummary.id)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.file_hash == file_hash)
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate statement upload")

    if extension != "csv":
        if model:
            try:
                model_info = await get_model_info(model)
            except ModelCatalogError as exc:
                raise_service_unavailable("Model catalog unavailable. Please try again.", cause=exc)
            if not model_info:
                raise_bad_request("Invalid model selection. Choose a model from /ai/models.")
            if not model_matches_modality(model_info, "image"):
                raise_bad_request("Selected model does not support image/PDF inputs.")

    statement_id = uuid4()
    request_id = _current_request_id()
    model_to_use = None if model == settings.ocr_model else model
    logger.info(
        "statement.upload.accepted",
        audit_event="statement.upload.accepted",
        request_id=request_id,
        user_id=str(user_id),
        statement_id=str(statement_id),
        filename=filename,
        file_type=extension,
        institution=institution or "(auto-detect)",
        model_requested=model,
        model_to_use=model_to_use,
        file_size_bytes=len(content),
        file_hash_prefix=file_hash_prefix,
        has_account_id=account_id is not None,
    )
    storage_key = build_statement_storage_key(
        statement_id=statement_id,
        file_hash=file_hash,
        extension=extension,
    )

    storage = StorageService()
    try:
        await run_in_threadpool(
            storage.upload_bytes,
            key=storage_key,
            content=content,
            content_type=mimetypes.guess_type(filename)[0] or "application/pdf",
        )
    except StorageError as exc:
        logger.error(
            "statement.upload.storage_failed",
            audit_event="statement.upload.storage_failed",
            request_id=request_id,
            statement_id=str(statement_id),
            phase="storage_upload_failed",
            progress=None,
            model_to_use=model_to_use,
            filename=filename,
            file_type=extension,
            file_size_bytes=len(content),
            file_hash_prefix=file_hash_prefix,
            error_type=type(exc).__name__,
            safe_error_message=_safe_error_message(str(exc)),
        )
        raise_service_unavailable(str(exc), cause=exc)
    logger.info(
        "statement.upload.storage_saved",
        audit_event="statement.upload.storage_saved",
        request_id=request_id,
        statement_id=str(statement_id),
        storage_key=storage_key,
        file_hash_prefix=file_hash_prefix,
    )

    statement = StatementSummary(
        id=statement_id,
        user_id=user_id,
        account_id=account_id,
        file_hash=file_hash,
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
        await db.flush()
        from src.services.evidence_graph_integration import EvidenceGraphIntegrationService

        # ``record_statement_upload`` reads ``original_filename`` (an ODS field that
        # the DWD envelope does not carry); supply it transiently for lineage only.
        statement.original_filename = filename
        await EvidenceGraphIntegrationService().record_statement_upload(
            db,
            user_id=user_id,
            statement=statement,
        )
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

    task = await submit_parse_pipeline(
        statement_id=statement_id,
        filename=filename,
        institution=institution,
        user_id=user_id,
        account_id=account_id,
        file_hash=file_hash,
        storage_key=storage_key,
        content=content,
        model=model_to_use,
        db=db,
        request_id=request_id,
    )
    if task is not None:
        _track_task(task)
    logger.info(
        "statement.parse.enqueued",
        audit_event="statement.parse.enqueued",
        request_id=request_id,
        statement_id=str(statement_id),
        filename=filename,
        file_type=extension,
        model_to_use=model_to_use,
    )

    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


@router.post("/{statement_id}/retry", response_model=BankStatementResponse)
async def retry_statement_parsing(
    statement_id: UUID,
    request: RetryParsingRequest | None = None,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> BankStatementResponse:
    """Retry parsing with a different model (e.g., stronger model for better accuracy)."""
    model_override = request.model if request else None

    statement = await _get_statement_or_404(db, statement_id, user_id)

    if statement.status not in (
        BankStatementStatus.PARSED,
        BankStatementStatus.REJECTED,
        BankStatementStatus.PARSING,
    ):
        raise_bad_request("Can only retry parsing for parsed, rejected, or stuck parsing statements")

    selected_model = model_override

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

    try:
        await _queue_statement_reparse(db, statement, user_id, model=selected_model)
    except StorageError as exc:
        raise_service_unavailable(f"Failed to fetch file from storage: {exc}", cause=exc)

    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


@router.get("", response_model=BankStatementListResponse)
async def list_statements(
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementListResponse:
    """List all statements for the current user."""
    result = await db.execute(
        select(StatementSummary).where(StatementSummary.user_id == user_id).order_by(StatementSummary.created_at.desc())
    )
    statements = result.scalars().all()

    total_result = await db.execute(
        select(func.count()).select_from(StatementSummary).where(StatementSummary.user_id == user_id)
    )
    total = total_result.scalar() or 0

    items = [await _compose_statement_response(db, s, user_id) for s in statements]
    return BankStatementListResponse(items=items, total=total)


@router.get("/pending-review", response_model=BankStatementListResponse)
async def list_pending_review(
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementListResponse:
    """List statements pending human review."""
    result = await db.execute(
        select(StatementSummary)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.status == BankStatementStatus.PARSED)
        .where(pending_stage1_review_filter())
        .order_by(StatementSummary.created_at.desc())
    )
    statements = result.scalars().all()

    total_result = await db.execute(
        select(func.count())
        .select_from(StatementSummary)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.status == BankStatementStatus.PARSED)
        .where(pending_stage1_review_filter())
    )
    total = total_result.scalar() or 0

    items = [await _compose_statement_response(db, s, user_id) for s in statements]
    return BankStatementListResponse(items=items, total=total)


@router.get("/{statement_id}", response_model=BankStatementResponse)
async def get_statement(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Get a statement with all its transactions."""
    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


@router.get("/{statement_id}/transactions", response_model=BankStatementTransactionListResponse)
async def list_statement_transactions(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementTransactionListResponse:
    """List transactions for a statement."""
    statement = await _get_statement_or_404(db, statement_id, user_id)
    transactions = await resolve_statement_transactions(db, statement)
    items = [AtomicTransactionResponse.from_atomic(t, statement.id) for t in transactions]
    return BankStatementTransactionListResponse(items=items, total=len(items))


def _brokerage_payload_from_statement(
    statement: StatementSummary,
    transactions: list[AtomicTransaction],
) -> dict:
    """Build an import payload from a parsed brokerage statement."""
    events = []
    for txn in transactions:
        direction = txn.direction.value if hasattr(txn.direction, "value") else txn.direction
        signed_amount = txn.amount if direction == "IN" else -txn.amount
        events.append(
            {
                "date": txn.txn_date.isoformat(),
                "description": txn.description,
                "amount": str(signed_amount),
                "currency": txn.currency or statement.currency,
                "raw_text": txn.description,
            }
        )

    return {
        "institution": statement.institution,
        "statement": {
            "institution": statement.institution,
            "period_end": statement.period_end.isoformat() if statement.period_end else None,
            "currency": statement.currency,
        },
        "transactions": events,
        "events": events,
    }


def _extract_brokerage_payload_from_metadata(metadata: dict | None) -> dict | None:
    """Return the structured extraction payload stored in Layer 1 metadata."""
    if not isinstance(metadata, dict):
        return None
    for key in ("extraction_payload", "parsed_payload", "payload"):
        payload = metadata.get(key)
        if isinstance(payload, dict):
            return payload
    return metadata if any(key in metadata for key in ("positions", "holdings", "securities")) else None


def _enrich_brokerage_payload_from_statement(payload: dict, statement: StatementSummary) -> dict:
    """Backfill statement metadata into a recovered extraction payload."""
    enriched = dict(payload)
    enriched.setdefault("institution", statement.institution)
    statement_payload = enriched.get("statement") if isinstance(enriched.get("statement"), dict) else {}
    statement_payload = dict(statement_payload)
    statement_payload.setdefault("institution", statement.institution)
    statement_payload.setdefault("period_end", statement.period_end.isoformat() if statement.period_end else None)
    statement_payload.setdefault("currency", statement.currency)
    enriched["statement"] = statement_payload
    return enriched


async def _brokerage_payload_from_persisted_extraction(
    db,
    *,
    statement: StatementSummary,
    uploaded_document: UploadedDocument | None,
    user_id: UUID,
) -> dict | None:
    """Load the persisted OCR extraction payload for statement-scoped imports."""
    payload = _extract_brokerage_payload_from_metadata(statement.extraction_metadata)
    if payload is not None:
        return _enrich_brokerage_payload_from_statement(payload, statement)

    if uploaded_document is None:
        return None
    payload = _extract_brokerage_payload_from_metadata(uploaded_document.extraction_metadata)
    if payload is None:
        return None
    return _enrich_brokerage_payload_from_statement(payload, statement)


def _brokerage_import_not_ready_reason(statement: StatementSummary, transaction_count: int) -> str:
    """Explain why a brokerage statement cannot be imported yet."""
    status_value = statement.status.value if hasattr(statement.status, "value") else str(statement.status)
    validation_error = statement.validation_error

    if status_value == BankStatementStatus.REJECTED.value:
        return f"Provider parsing failed before brokerage import: {validation_error or 'statement rejected'}"
    if status_value in {BankStatementStatus.UPLOADED.value, BankStatementStatus.PARSING.value}:
        return "Provider parsing has not completed; statement must be parsed before brokerage import"

    return f"Statement must be parsed before importing brokerage positions; current status={status_value}"


@router.post("/{statement_id}/brokerage/import", response_model=BrokerageImportResponse)
async def import_brokerage_statement_positions(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> BrokerageImportResponse:
    """Import portfolio positions from an already parsed brokerage statement."""
    statement = await _get_statement_or_404(db, statement_id, user_id)
    transactions = await resolve_statement_transactions(db, statement)

    if statement.status not in (BankStatementStatus.PARSED, BankStatementStatus.APPROVED):
        raise_bad_request(_brokerage_import_not_ready_reason(statement, len(transactions)))

    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    source_filename = uploaded_document.original_filename if uploaded_document else statement.file_hash

    payload = await _brokerage_payload_from_persisted_extraction(
        db, statement=statement, uploaded_document=uploaded_document, user_id=user_id
    )
    if payload is None:
        payload = _brokerage_payload_from_statement(statement, transactions)
    request_id = _current_request_id()
    source_document_id = str(statement.uploaded_document_id or statement.id)
    logger.info(
        "statement.brokerage_import.started",
        audit_event="statement.brokerage_import.started",
        request_id=request_id,
        statement_id=str(statement.id),
        phase="brokerage_import_started",
        model_to_use=None,
        broker=statement.institution,
        parsed_positions=len(transactions),
    )
    try:
        import_result = await _BROKERAGE_IMPORT_SERVICE.import_positions(
            db,
            user_id=user_id,
            payload=payload,
            filename=source_filename,
            source_document_id=source_document_id,
        )
        await db.commit()
    except Exception as exc:
        logger.exception(
            "statement.brokerage_import.failed",
            audit_event="statement.brokerage_import.failed",
            request_id=request_id,
            statement_id=str(statement.id),
            phase="brokerage_import_failed",
            model_to_use=None,
            error_type=type(exc).__name__,
            safe_error_message=_safe_error_message(str(exc)),
        )
        await db.rollback()
        raise
    logger.info(
        "statement.brokerage_import.completed",
        audit_event="statement.brokerage_import.completed",
        request_id=request_id,
        statement_id=str(statement.id),
        phase="brokerage_import_completed",
        model_to_use=None,
        broker=import_result.broker,
        parsed_positions=import_result.parsed_positions,
        created_atomic_positions=import_result.created_atomic_positions,
        existing_atomic_positions=import_result.existing_atomic_positions,
        reconcile_created=import_result.reconcile_created,
        reconcile_updated=import_result.reconcile_updated,
        reconcile_disposed=import_result.reconcile_disposed,
    )
    return BrokerageImportResponse(**import_result.__dict__)


@router.post("/{statement_id}/approve", response_model=BankStatementResponse, deprecated=True)
async def approve_statement(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """[Deprecated] Approve via Stage 1 validation flow.

    Compatibility note: decision payload is accepted but ignored.
    """
    await _get_statement_or_404(db, statement_id, user_id)

    try:
        await approve_statement_svc(db, statement_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()

    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


@router.post("/{statement_id}/reject", response_model=BankStatementResponse, deprecated=True)
async def reject_statement(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """[Deprecated] Reject via Stage 1 validation flow."""
    await _get_statement_or_404(db, statement_id, user_id)

    try:
        await reject_statement_svc(db, statement_id, user_id, reason=decision.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()

    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


@router.delete("/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_statement(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a statement."""
    statement = await _get_statement_or_404(db, statement_id, user_id)

    # Resolve the MinIO object key via the ODS document and delete from storage.
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    storage_key = uploaded_document.file_path if uploaded_document else None
    if storage_key:
        storage = StorageService()
        try:
            await run_in_threadpool(storage.delete_object, storage_key)
        except StorageError as exc:
            logger.error(
                "Failed to delete file from storage",
                error=str(exc),
                error_id=ErrorIds.STORAGE_DELETE_FAILED,
                file_path=storage_key,
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
    statement = await _get_statement_or_404(db, statement_id, user_id)
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    transactions = await resolve_statement_transactions(db, statement)

    pdf_url = None
    if uploaded_document is not None:
        try:
            storage = StorageService()
            pdf_url = await asyncio.to_thread(
                storage.generate_presigned_url,
                key=uploaded_document.file_path,
                expires_in=settings.statement_review_presign_expiry_seconds,
            )
        except StorageError as exc:
            logger.warning(
                "Could not generate presigned URL for review",
                error=str(exc),
                statement_id=str(statement_id),
            )

    validation_result = await validate_balance_chain(db, statement_id)

    response_data = {
        "id": statement.id,
        "user_id": statement.user_id,
        "account_id": statement.account_id,
        "file_path": uploaded_document.file_path if uploaded_document else "",
        "original_filename": uploaded_document.original_filename if uploaded_document else "",
        "institution": statement.institution,
        "account_last4": statement.account_last4,
        "currency": statement.currency,
        "period_start": statement.period_start,
        "period_end": statement.period_end,
        "opening_balance": statement.opening_balance,
        "closing_balance": statement.closing_balance,
        "status": statement.status,
        "confidence_score": statement.confidence_score,
        "balance_validated": statement.balance_validated,
        "validation_error": statement.validation_error,
        "stage1_status": statement.stage1_status,
        "stage1_reviewed_at": statement.stage1_reviewed_at,
        "manual_opening_balance": statement.manual_opening_balance,
        "created_at": statement.created_at,
        "updated_at": statement.updated_at,
        "transactions": [AtomicTransactionResponse.from_atomic(t, statement.id) for t in transactions],
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


@router.post("/{statement_id}/review/approve", response_model=Stage1ApprovalResponse)
async def approve_statement_stage1(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
    request: Annotated[Stage1ApprovalRequest | None, Body()] = None,
) -> Stage1ApprovalResponse:
    """Stage 1: Approve statement with balance validation."""
    try:
        statement = await _get_statement_or_404(db, statement_id, user_id)
        if request and request.create_account_if_missing and not statement.account_id:
            await _create_statement_account_from_confirmation(db, statement, user_id)
        elif not statement.account_id:
            await resolve_statement_posting_account(db, statement, user_id)

        statement = await approve_statement_svc(db, statement_id, user_id)
        created_count = await auto_create_posted_entries_for_statement(db, statement, user_id)
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    statement = await _get_statement_or_404(db, statement_id, user_id)
    response = await _compose_statement_response(db, statement, user_id)
    return Stage1ApprovalResponse(**response.model_dump(), journal_entries_created=created_count)


@router.post("/{statement_id}/review/reject", response_model=BankStatementResponse)
async def reject_statement_stage1(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Stage 1: Reject statement."""
    try:
        statement = await reject_statement_svc(db, statement_id, user_id, reason=decision.notes)
        await db.commit()
        await db.refresh(statement)
        await _queue_statement_reparse(db, statement, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as exc:
        raise_service_unavailable(f"Failed to fetch file from storage: {exc}", cause=exc)

    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


@router.post("/{statement_id}/review/edit", response_model=Stage1ApprovalResponse)
async def edit_and_approve_statement(
    statement_id: UUID,
    request: EditAndApproveRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> Stage1ApprovalResponse:
    """Stage 1: Edit transactions and approve."""
    edits_data = [{**e.model_dump(), "txn_id": str(e.txn_id)} for e in request.edits]
    try:
        statement = await edit_and_approve(db, statement_id, user_id, edits_data)
        created_count = await auto_create_posted_entries_for_statement(db, statement, user_id)
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    statement = await _get_statement_or_404(db, statement_id, user_id)
    response = await _compose_statement_response(db, statement, user_id)
    return Stage1ApprovalResponse(**response.model_dump(), journal_entries_created=created_count)


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

    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


async def wait_for_parse_tasks() -> None:
    """Wait for all pending background parsing tasks to complete. Useful for tests."""
    if _PENDING_PARSE_TASKS:
        await asyncio.gather(*_PENDING_PARSE_TASKS, return_exceptions=True)
