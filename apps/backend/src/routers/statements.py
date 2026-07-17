"""Statement extraction API router."""

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.composition import compose_statement_posting_dependencies
from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.extraction import (
    BrokeragePositionImportService,
    ParseJob,
    UploadedDocument,
    _brokerage_import_not_ready_reason,
    _brokerage_payload_from_persisted_extraction,
    _brokerage_payload_from_statement,
    approve_statement_workflow,
    auto_create_posted_entries_for_statement,
    edit_and_approve,
    pending_stage1_review_filter,
    register_statement_source,
    reject_statement_workflow,
    resolve_statement_posting_account,
    resolve_statement_transactions,
    set_opening_balance,
    submit_parse_pipeline,
    validate_balance_chain,
)
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from src.llm import LitellmCatalog, Modality
from src.observability import ErrorIds, ensure_request_id, get_logger, safe_error_message
from src.platform import (
    get_owned_or_404,
    raise_bad_request,
    raise_internal_error,
    raise_not_found,
    raise_service_unavailable,
    raise_too_large,
)
from src.runtime import StorageError, StorageService
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

router = APIRouter(prefix="/statements", tags=["statements"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
logger = get_logger(__name__)

# Track background parsing tasks to avoid garbage collection
_PENDING_PARSE_TASKS: set[asyncio.Task[None]] = set()
_BROKERAGE_IMPORT_SERVICE = BrokeragePositionImportService()


def _track_task(task: asyncio.Task[None]) -> None:
    _PENDING_PARSE_TASKS.add(task)
    task.add_done_callback(_PENDING_PARSE_TASKS.discard)


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
    return await get_owned_or_404(db, StatementSummary, statement_id, user_id, name="Statement")


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
    request_id = ensure_request_id()
    model_to_use = None if model == settings.ocr_model else model
    task = await submit_parse_pipeline(
        job=ParseJob(
            statement_id=statement.id,
            filename=filename,
            institution=statement.institution,
            user_id=user_id,
            account_id=statement.account_id,
            file_hash=statement.file_hash,
            storage_key=storage_key,
            model=model_to_use,
            request_id=request_id,
        ),
        content=content,
        db=db,
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

    currency = (statement.currency or "").strip().upper()
    if not currency:
        raise ValueError("Statement currency required before creating an account. Confirm the source currency first.")
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
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """
    Upload a financial statement and enqueue parsing.

    Supported file types: PDF, CSV, PNG, JPG. Model is optional for PDF/image uploads;
    omitted model uses the OCR-first default pipeline.

    Institution is optional for PDF/image uploads (AI auto-detects it from the
    document). It is **required** for CSV uploads — the institution cannot be
    auto-detected from CSV content, so a missing institution is rejected
    synchronously with HTTP 400 rather than accepted and rejected asynchronously
    by the parse worker (#1141 / #1087).
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

    # AC13.18.6 (#1141 / #1087): CSV parsing cannot auto-detect the institution the
    # way PDF/image vision extraction can, so a CSV without an institution can only
    # fail later inside the async parse worker ("Institution is required for CSV
    # parsing"), leaving an orphaned PARSING record. Reject it synchronously here
    # with an actionable 400 instead of accepting (202) then rejecting async.
    # Normalize the institution up front: persist/pass the STRIPPED value so that
    # leading/trailing whitespace can't break CSV institution routing downstream
    # in ``ExtractionService._parse_csv_content()`` (#1141 / #1087).
    institution = institution.strip() if institution else None
    if extension == "csv" and not institution:
        raise_bad_request("Institution is required for CSV uploads. Please select an institution and retry.")

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
            spec = await LitellmCatalog().get(model)
            if spec is None:
                raise_bad_request("Invalid model selection. Choose a model from /llm/catalog.")
            if not spec.accepts(Modality.IMAGE):
                raise_bad_request("Selected model does not support image/PDF inputs.")

    statement_id = uuid4()
    request_id = ensure_request_id()
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
            safe_error_message=safe_error_message(str(exc)),
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
        await register_statement_source(
            db,
            statement=statement,
            storage_key=storage_key,
            original_filename=filename,
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
        job=ParseJob(
            statement_id=statement_id,
            filename=filename,
            institution=institution,
            user_id=user_id,
            account_id=account_id,
            file_hash=file_hash,
            storage_key=storage_key,
            model=model_to_use,
            request_id=request_id,
        ),
        content=content,
        db=db,
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
    *,
    db: DbSession,
    user_id: CurrentUserId,
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
        spec = await LitellmCatalog().get(model_override)
        if spec is None:
            raise_bad_request("Invalid model selection. Choose a model from /llm/catalog.")
        if not spec.accepts(Modality.IMAGE):
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


@router.get("/{statement_id}/document")
async def get_statement_document(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> Response:
    """Stream the original uploaded document for a statement, same-origin.

    AC16.33.5: the Stage 1 review PDF preview embeds this authenticated,
    same-origin endpoint as a ``blob:`` object URL instead of a cross-origin
    object-storage URL the CSP cannot frame. Auth is the standard Bearer
    dependency; the frontend fetches the bytes via ``apiDownload`` (which
    carries the token) and never points an iframe directly at storage.
    """
    statement = await _get_statement_or_404(db, statement_id, user_id)
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    if uploaded_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No uploaded document is associated with this statement",
        )

    try:
        storage = StorageService()
        content = await asyncio.to_thread(storage.get_object, uploaded_document.file_path)
    except StorageError as exc:
        logger.warning(
            "Could not fetch statement document",
            error=str(exc),
            statement_id=str(statement_id),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Statement document is temporarily unavailable",
        ) from exc

    media_type = mimetypes.guess_type(uploaded_document.original_filename)[0] or "application/pdf"
    # Inline so the browser renders the document in the review iframe rather
    # than forcing a download; ``frame-ancestors 'none'`` still blocks framing
    # from foreign origins.
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


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


# Synchronous 200: the import runs inline and returns the full BrokerageImportResponse
# (counts + reconciliation results), so the operation is complete on response — not a
# 202 background job (cf. #1099 AC-platform.29.1).
@router.post(
    "/{statement_id}/brokerage/import",
    response_model=BrokerageImportResponse,
    status_code=status.HTTP_200_OK,
)
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

    payload = _brokerage_payload_from_persisted_extraction(statement=statement, uploaded_document=uploaded_document)
    if payload is None:
        payload = _brokerage_payload_from_statement(statement, transactions)
    request_id = ensure_request_id()
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
        # #1484: anchor the statement to the broker account the import reconciled
        # into, closing the source→account traceability gap (a bank statement is
        # linked the same way during posting). Only set it when not already linked.
        if statement.account_id is None and import_result.account_id is not None:
            statement.account_id = import_result.account_id
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
            safe_error_message=safe_error_message(str(exc)),
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
    # Report the statement's effective anchor: prefer the (possibly pre-existing)
    # statement.account_id over the import's freshly-resolved one, so the response
    # never says null while the statement is in fact linked (#1484).
    return BrokerageImportResponse(
        **{**import_result.__dict__, "account_id": statement.account_id or import_result.account_id}
    )


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
                # #1391: the review URL is consumed by a browser, so it must use
                # the public endpoint. Without this the presigned URL points at the
                # internal object-storage host and the preview cannot load.
                public=True,
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

        created_count = await approve_statement_workflow(
            db,
            statement_id,
            user_id,
            dependencies=compose_statement_posting_dependencies(),
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

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
        statement = await reject_statement_workflow(db, statement_id, user_id, reason=decision.notes)
        await _queue_statement_reparse(db, statement, user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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
        created_count = await auto_create_posted_entries_for_statement(
            db,
            statement,
            user_id,
            dependencies=compose_statement_posting_dependencies(),
        )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    statement = await _get_statement_or_404(db, statement_id, user_id)
    return await _compose_statement_response(db, statement, user_id)


async def wait_for_parse_tasks() -> None:
    """Wait for all pending background parsing tasks to complete. Useful for tests."""
    if _PENDING_PARSE_TASKS:
        await asyncio.gather(*_PENDING_PARSE_TASKS, return_exceptions=True)
