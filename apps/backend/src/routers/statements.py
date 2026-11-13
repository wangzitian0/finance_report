"""Statement extraction API router."""

import asyncio
import hashlib
import mimetypes
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.composition import (
    auto_fill_default_statement_dispositions,
    compose_statement_posting_dependencies,
)
from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.extraction import (
    STATEMENT_RESOLVED_TRANSACTIONS_ATTR,
    AtomicTransaction,
    BROKERAGE_IMPORTABLE_STATUSES,
    BankStatementStatus,
    BrokerageImportRejectedError,
    BrokeragePositionImportService,
    HintsNotApplicable,
    ParseJob,
    RetireStatementCommand,
    ReviewedStatementEnvelopeCommand,
    ReviewedStatementEnvelopeConflict,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    StatementPostingOutcome,
    StatementPostingStatus,
    StatementRunRecord,
    StatementStatusChanged,
    StatementSummary,
    UploadedDocument,
    _brokerage_import_not_ready_reason,
    _brokerage_payload_from_persisted_extraction,
    _brokerage_payload_from_statement,
    approve_statement_workflow,
    classification_suggestions,
    clear_brokerage_import_failure,
    confirm_reviewed_statement_envelope,
    create_run,
    current_reviewed_statement_envelope,
    get_current_statement_extraction_result,
    is_bank_custody_source,
    list_runs,
    pending_stage1_review_filter,
    record_brokerage_import_failure,
    register_statement_source,
    reject_statement_workflow,
    resolve_bank_custody_account,
    resolve_statement_posting_account,
    resolve_statement_transactions,
    retire_statement,
    set_opening_balance,
    start_user_extract_run,
    submit_parse_pipeline,
    supports_reviewed_statement_envelope,
    validate_balance_chain,
)
from src.ledger import Account, AccountType, account_service
from src.llm import LitellmCatalog, Modality
from src.observability import ErrorIds, ensure_request_id, get_logger, safe_error_message
from src.platform import (
    raise_bad_request,
    raise_conflict,
    raise_internal_error,
    raise_not_found,
    raise_service_unavailable,
    raise_too_large,
)
from src.portfolio import PositionServiceError
from src.runtime import StorageError, StorageService
from src.schemas import (
    AtomicTransactionResponse,
    BankStatementListResponse,
    BankStatementResponse,
    BankStatementTransactionListResponse,
    StatementDecisionRequest,
    StatementRunListResponse,
    StatementRunRequest,
)
from src.schemas.extraction import compose_statement_list_item_response, compose_statement_response
from src.schemas.portfolio import BrokerageImportResponse
from src.schemas.review import (
    BalanceValidationResult,
    ReviewedStatementEnvelopeRequest,
    ReviewedStatementEnvelopeResponse,
    SetOpeningBalanceRequest,
    Stage1ApprovalRequest,
    Stage1ApprovalResponse,
    StatementReviewResponse,
)

router = APIRouter(prefix="/statements", tags=["statements"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = {"pdf", "csv", "png", "jpg", "jpeg"}
# A user can run the extraction again from these statuses.
_RERUN_STATUSES = frozenset({BankStatementStatus.PARSED, BankStatementStatus.REJECTED, BankStatementStatus.PARSING})
# A reject can start from these statuses. A retired or uploaded statement has no parse to run again.
_REJECT_STATUSES = _RERUN_STATUSES | {BankStatementStatus.APPROVED}
logger = get_logger(__name__)

_PENDING_PARSE_TASKS: set[asyncio.Task[None]] = set()
_BROKERAGE_IMPORT_SERVICE = BrokeragePositionImportService()


def _track_task(task: asyncio.Task[None]) -> None:
    _PENDING_PARSE_TASKS.add(task)
    task.add_done_callback(_PENDING_PARSE_TASKS.discard)


def _posting_count_or_conflict(outcome: StatementPostingOutcome) -> int:
    if outcome.status is StatementPostingStatus.REVIEW_REQUIRED:
        raise_conflict(f"Economic review required: {', '.join(outcome.review_reasons)}")
    return outcome.created_count


async def _validate_vision_model(model: str | None) -> None:
    if not model:
        return
    spec = await LitellmCatalog().get(model)
    if spec is None:
        raise_bad_request("Invalid model selection. Choose a model from /llm/catalog.")
    if not spec.accepts(Modality.IMAGE):
        raise_bad_request("Selected model does not support image/PDF inputs.")


async def _resolve_uploaded_document(
    db: AsyncSession, statement: StatementSummary, user_id: UUID
) -> UploadedDocument | None:
    if statement.uploaded_document_id is not None:
        doc = await db.get(UploadedDocument, statement.uploaded_document_id)
        if doc is not None and doc.user_id == user_id:
            return doc
    return (
        await db.execute(
            select(UploadedDocument).where(
                UploadedDocument.user_id == user_id, UploadedDocument.file_hash == statement.file_hash
            )
        )
    ).scalar_one_or_none()


async def _resolve_uploaded_documents(
    db: AsyncSession, statements: Sequence[StatementSummary], user_id: UUID
) -> dict[UUID, UploadedDocument | None]:
    doc_ids = {s.uploaded_document_id for s in statements if s.uploaded_document_id is not None}
    by_id = (
        {
            d.id: d
            for d in (
                await db.execute(
                    select(UploadedDocument).where(
                        UploadedDocument.user_id == user_id, UploadedDocument.id.in_(doc_ids)
                    )
                )
            ).scalars()
        }
        if doc_ids
        else {}
    )
    resolved: dict[UUID, UploadedDocument | None] = {}
    missing: list[StatementSummary] = []
    for s in statements:
        doc = by_id.get(s.uploaded_document_id) if s.uploaded_document_id is not None else None
        resolved[s.id] = doc
        if doc is None:
            missing.append(s)
    if missing:
        by_hash = {
            d.file_hash: d
            for d in (
                await db.execute(
                    select(UploadedDocument).where(
                        UploadedDocument.user_id == user_id,
                        UploadedDocument.file_hash.in_({s.file_hash for s in missing}),
                    )
                )
            ).scalars()
        }
        for s in missing:
            resolved[s.id] = by_hash.get(s.file_hash)
    return resolved


async def _compose_statement_response(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    transactions: list[AtomicTransaction] | None = None,
) -> BankStatementResponse:
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    if transactions is None:
        transactions = await resolve_statement_transactions(db, statement)
    suggestions = await classification_suggestions(db, [t.id for t in transactions])
    return compose_statement_response(statement, uploaded_document, transactions, suggestions=suggestions)


async def _get_statement_or_404(db: AsyncSession, statement_id: UUID, user_id: UUID) -> StatementSummary:
    stmt = (
        await db.execute(
            select(StatementSummary).where(
                StatementSummary.id == statement_id,
                StatementSummary.user_id == user_id,
                StatementSummary.status != BankStatementStatus.RETIRED,
            )
        )
    ).scalar_one_or_none()
    if stmt is None:
        raise_not_found("Statement")
    return stmt


async def _list_statements_by_where(db: AsyncSession, user_id: UUID, *clauses) -> BankStatementListResponse:
    statements = (
        (await db.execute(select(StatementSummary).where(*clauses).order_by(StatementSummary.created_at.desc())))
        .scalars()
        .all()
    )
    total = (await db.execute(select(func.count()).select_from(StatementSummary).where(*clauses))).scalar() or 0
    documents = await _resolve_uploaded_documents(db, statements, user_id)
    return BankStatementListResponse(
        items=[compose_statement_list_item_response(s, documents[s.id]) for s in statements],
        total=total,
    )


def _envelope_response(envelope, digest: str) -> ReviewedStatementEnvelopeResponse:
    return ReviewedStatementEnvelopeResponse(
        id=envelope.id,
        source_result_digest=digest,
        account_id=envelope.account_id,
        currency=envelope.currency,
        period_start=envelope.period_start,
        period_end=envelope.period_end,
        opening_balance=envelope.opening_balance,
        closing_balance=envelope.closing_balance,
        rationale=envelope.rationale,
        review_trace_record_id=envelope.review_trace_record_id,
        created_at=envelope.created_at,
    )


async def _enqueue_parse_job(
    db: AsyncSession,
    *,
    job: ParseJob,
    content: bytes,
    file_type: str,
) -> None:
    task = await submit_parse_pipeline(job=job, content=content, db=db)
    if task is not None:
        _track_task(task)
    logger.info(
        "statement.parse.enqueued",
        audit_event="statement.parse.enqueued",
        request_id=job.request_id,
        statement_id=str(job.statement_id),
        filename=job.filename,
        file_type=file_type,
        model_to_use=job.model,
    )


async def _queue_statement_reparse(
    db: DbSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    allowed_statuses: frozenset[BankStatementStatus],
    model: str | None = None,
    hints: RunHints | None = None,
    strict_hints: bool = False,
    while_pending: Callable[[], Awaitable[StatementSummary]] | None = None,
) -> UUID:
    """Start a user rerun of the statement, commit it, dispatch its job and return the id of its run.

    `start_user_extract_run` owns the order of the steps and the rules: the CSV rule, the storage read, the row
    lock, the status check, the run insert. This function maps its errors to HTTP and dispatches the job.
    The reject passes `while_pending`, so its writes and the run commit together.
    """
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    if uploaded_document is None:
        raise StorageError("Source document is no longer available for reparse")
    storage_key = uploaded_document.file_path
    filename = uploaded_document.original_filename
    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    request_id = ensure_request_id()
    model_to_use = None if model == settings.multimodal_model else model
    try:
        started = await start_user_extract_run(
            db,
            statement_id=statement.id,
            user_id=user_id,
            file_type=file_type,
            hints=hints or RunHints(),
            model=model_to_use,
            allowed_statuses=allowed_statuses,
            strict_hints=strict_hints,
            load_content=lambda: run_in_threadpool(StorageService().get_object, storage_key),
            while_pending=while_pending,
        )
    except HintsNotApplicable as exc:
        raise_bad_request(str(exc), cause=exc)
    except StatementStatusChanged:
        await db.rollback()
        raise_conflict("The statement changed while the run started. Reload the page and try again.")
    await db.commit()
    statement = started.statement
    await db.refresh(statement)
    await _enqueue_parse_job(
        db,
        job=ParseJob(
            statement_id=statement.id,
            run_id=started.run_id,
            filename=filename,
            institution=None if statement.institution == "Pending Detection" else statement.institution,
            user_id=user_id,
            account_id=statement.account_id,
            file_hash=statement.file_hash,
            storage_key=storage_key,
            model=model_to_use,
            request_id=request_id,
        ),
        content=started.content,
        file_type=file_type,
    )
    return started.run_id


async def _create_statement_account_from_confirmation(
    db: DbSession, statement: StatementSummary, user_id: UUID
) -> Account:
    source = await get_current_statement_extraction_result(db, user_id=user_id, statement_id=statement.id)
    document = await _resolve_uploaded_document(db, statement, user_id)
    if (
        is_bank_custody_source(source, document)
        and statement.institution
        and statement.account_last4
        and statement.currency
    ):
        resolved = await resolve_bank_custody_account(
            db,
            user_id=user_id,
            institution=statement.institution,
            account_last4=statement.account_last4,
            currency=statement.currency,
            account_id=statement.account_id,
        )
        statement.account_id = resolved.id
        await db.flush()
        return resolved
    if statement.account_id:
        account = (
            await db.execute(select(Account).where(Account.id == statement.account_id, Account.user_id == user_id))
        ).scalar_one_or_none()
        if account:
            return account
        raise ValueError("Statement account mapping is invalid. Confirm the target account before posting.")

    currency = (statement.currency or "").strip().upper()
    if not currency:
        raise ValueError("Statement currency required before creating an account. Confirm the source currency first.")
    account_name = (statement.institution or "").strip() or "Statement Account"
    if statement.account_last4:
        account_name = f"{account_name} *{statement.account_last4.strip()}"
    source_filename = document.original_filename if document else statement.file_hash

    async def _find_statement_account(session: AsyncSession) -> Account | None:
        return (
            await session.execute(
                select(Account)
                .where(
                    Account.user_id == user_id,
                    Account.name == account_name,
                    Account.type == AccountType.ASSET,
                    Account.currency == currency,
                    Account.is_active.is_(True),
                )
                .order_by(Account.created_at, Account.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    created = await account_service.find_or_create_account(
        db,
        user_id=user_id,
        find=_find_statement_account,
        build=lambda: Account(
            user_id=user_id,
            name=account_name,
            type=AccountType.ASSET,
            currency=currency,
            code="AUTO-BANK",
            description=f"Created from confirmed statement import {source_filename}",
        ),
    )
    statement.account_id = created.id
    await db.flush()
    return created


def build_statement_storage_key(*, statement_id: UUID, file_hash: str, extension: str) -> str:
    safe_extension = extension.lower() if extension.lower() in _ALLOWED_EXTENSIONS else "bin"
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
    """Upload a financial statement and enqueue parsing."""
    filename = Path(file.filename or "unknown").name or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    if extension not in _ALLOWED_EXTENSIONS:
        raise_bad_request(f"Unsupported file type: {extension}")

    institution = institution.strip() if institution else None
    if extension == "csv" and not institution:
        raise_bad_request("Institution is required for CSV uploads. Please select an institution and retry.")

    if account_id is not None:
        if (
            await db.execute(select(Account.id).where(Account.id == account_id, Account.user_id == user_id))
        ).scalar_one_or_none() is None:
            raise_not_found("Account")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise_too_large("File exceeds 10MB limit")

    file_hash = hashlib.sha256(content).hexdigest()
    if (
        await db.execute(
            select(StatementSummary.id).where(
                StatementSummary.user_id == user_id, StatementSummary.file_hash == file_hash
            )
        )
    ).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate statement upload")

    if extension != "csv":
        await _validate_vision_model(model)

    statement_id = uuid4()
    request_id = ensure_request_id()
    model_to_use = None if model == settings.multimodal_model else model
    file_hash_prefix = file_hash[:12]
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
    storage_key = build_statement_storage_key(statement_id=statement_id, file_hash=file_hash, extension=extension)
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
    )
    db.add(statement)
    try:
        await db.flush()
        await register_statement_source(db, statement=statement, storage_key=storage_key, original_filename=filename)
        run = await create_run(
            db,
            statement_id=statement_id,
            user_id=user_id,
            kind=RunKind.EXTRACT,
            actor_kind=RunActorKind.USER,
            trigger=RunTrigger.UPLOAD,
            hints=RunHints(),
            model=model_to_use,
        )
        run_id = run.id
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

    await _enqueue_parse_job(
        db,
        job=ParseJob(
            statement_id=statement_id,
            run_id=run_id,
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
        file_type=extension,
    )
    return await _compose_statement_response(db, await _get_statement_or_404(db, statement_id, user_id), user_id)


@router.post("/{statement_id}/runs", response_model=StatementRunRecord, status_code=status.HTTP_202_ACCEPTED)
async def create_statement_run(
    statement_id: UUID,
    request: StatementRunRequest,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> StatementRunRecord:
    """Run the extraction of a statement again, with optional hints and a model override.

    The actor of the run is the authenticated user. An active run gives 409 with `active_run_id`.
    """
    statement = await _get_statement_or_404(db, statement_id, user_id)
    if statement.status not in _RERUN_STATUSES:
        raise_bad_request("Can only run again for parsed, rejected, or stuck parsing statements")
    await _validate_vision_model(request.model)
    try:
        run_id = await _queue_statement_reparse(
            db,
            statement,
            user_id,
            model=request.model,
            hints=request.hints,
            allowed_statuses=_RERUN_STATUSES,
            strict_hints=True,
        )
    except StorageError as exc:
        raise_service_unavailable(f"Failed to fetch file from storage: {exc}", cause=exc)
    runs = await list_runs(db, statement_id, user_id)
    return next(run for run in runs if run.id == run_id)


@router.get("/{statement_id}/runs", response_model=StatementRunListResponse)
async def list_statement_runs(
    statement_id: UUID, db: DbSession, user_id: CurrentUserId
) -> StatementRunListResponse:
    """List the runs of a statement by attempt number, with their hints, actor, state and error."""
    await _get_statement_or_404(db, statement_id, user_id)
    runs = await list_runs(db, statement_id, user_id)
    return StatementRunListResponse(items=runs, total=len(runs))


@router.get("", response_model=BankStatementListResponse)
async def list_statements(db: DbSession, user_id: CurrentUserId) -> BankStatementListResponse:
    """List non-retired statements for the current user."""
    return await _list_statements_by_where(
        db, user_id, StatementSummary.user_id == user_id, StatementSummary.status != BankStatementStatus.RETIRED
    )


@router.get("/pending-review", response_model=BankStatementListResponse)
async def list_pending_review(db: DbSession, user_id: CurrentUserId) -> BankStatementListResponse:
    """List statements pending Stage 1 human review."""
    return await _list_statements_by_where(
        db,
        user_id,
        StatementSummary.user_id == user_id,
        StatementSummary.status == BankStatementStatus.PARSED,
        pending_stage1_review_filter(),
    )


@router.get("/{statement_id}", response_model=BankStatementResponse)
async def get_statement(statement_id: UUID, db: DbSession, user_id: CurrentUserId) -> BankStatementResponse:
    """Get a statement with all its transactions."""
    return await _compose_statement_response(db, await _get_statement_or_404(db, statement_id, user_id), user_id)


@router.get("/{statement_id}/document")
async def get_statement_document(statement_id: UUID, db: DbSession, user_id: CurrentUserId) -> Response:
    """Stream the original uploaded document for a statement, same-origin."""
    statement = await _get_statement_or_404(db, statement_id, user_id)
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    if uploaded_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No uploaded document is associated with this statement",
        )
    try:
        content = await asyncio.to_thread(StorageService().get_object, uploaded_document.file_path)
    except StorageError as exc:
        logger.warning("Could not fetch statement document", error=str(exc), statement_id=str(statement_id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Statement document is temporarily unavailable",
        ) from exc
    media_type = mimetypes.guess_type(uploaded_document.original_filename)[0] or "application/pdf"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{statement_id}/transactions", response_model=BankStatementTransactionListResponse)
async def list_statement_transactions(
    statement_id: UUID, db: DbSession, user_id: CurrentUserId
) -> BankStatementTransactionListResponse:
    """List transactions for a statement."""
    statement = await _get_statement_or_404(db, statement_id, user_id)
    transactions = await resolve_statement_transactions(db, statement)
    suggestions = await classification_suggestions(db, [t.id for t in transactions])
    items = [
        AtomicTransactionResponse.from_atomic(
            t, statement.id, suggestion=suggestions.get(t.id), source_row=getattr(t, "source_row", idx + 1)
        )
        for idx, t in enumerate(transactions)
    ]
    return BankStatementTransactionListResponse(items=items, total=len(items))


@router.post(
    "/{statement_id}/brokerage/import",
    response_model=BrokerageImportResponse,
    status_code=status.HTTP_200_OK,
)
async def import_brokerage_statement_positions(
    statement_id: UUID, db: DbSession, user_id: CurrentUserId
) -> BrokerageImportResponse:
    """Import portfolio positions from a parsed brokerage statement."""
    statement = await _get_statement_or_404(db, statement_id, user_id)
    transactions = await resolve_statement_transactions(db, statement)
    if statement.status not in BROKERAGE_IMPORTABLE_STATUSES:
        raise_bad_request(_brokerage_import_not_ready_reason(statement, len(transactions)))

    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    source_filename = uploaded_document.original_filename if uploaded_document else statement.file_hash
    payload = _brokerage_payload_from_persisted_extraction(
        statement=statement, uploaded_document=uploaded_document
    ) or _brokerage_payload_from_statement(statement, transactions)
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
        if statement.account_id is None and import_result.account_id is not None:
            statement.account_id = import_result.account_id
        await clear_brokerage_import_failure(db, statement_id=statement_id, user_id=user_id)
        await db.commit()
    except Exception as exc:
        is_rejected = isinstance(exc, BrokerageImportRejectedError | PositionServiceError)
        (logger.warning if is_rejected else logger.exception)(
            "statement.brokerage_import.failed",
            audit_event="statement.brokerage_import.failed",
            request_id=request_id,
            statement_id=str(statement_id),
            phase="brokerage_import_failed",
            model_to_use=None,
            error_type=type(exc).__name__,
            safe_error_message=safe_error_message(str(exc)),
        )
        await db.rollback()
        try:
            await record_brokerage_import_failure(
                db,
                statement_id=statement_id,
                user_id=user_id,
                request_id=request_id,
                reason=exc.message
                if isinstance(exc, BrokerageImportRejectedError)
                else (str(exc) if is_rejected else None),
            )
            await db.commit()
        except Exception as record_exc:  # noqa: BLE001
            await db.rollback()
            logger.warning(
                "statement.brokerage_import.failure_not_recorded",
                request_id=request_id,
                statement_id=str(statement_id),
                error_type=type(record_exc).__name__,
            )
        if isinstance(exc, PositionServiceError):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
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
    return BrokerageImportResponse(
        **{**import_result.__dict__, "account_id": statement.account_id or import_result.account_id}
    )


@router.delete("/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_statement(statement_id: UUID, db: DbSession, user_id: CurrentUserId) -> None:
    """Retire a statement from product views while retaining source history."""
    try:
        await retire_statement(
            db,
            RetireStatementCommand(statement_id=statement_id, user_id=user_id),
            dependencies=compose_statement_posting_dependencies(),
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise_not_found("Statement", cause=exc)


@router.get("/{statement_id}/review", response_model=StatementReviewResponse)
async def get_statement_for_review(
    statement_id: UUID, db: DbSession, user_id: CurrentUserId
) -> StatementReviewResponse:
    """Get Stage 1 review data for a statement."""
    statement = await _get_statement_or_404(db, statement_id, user_id)
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    transactions = await resolve_statement_transactions(db, statement)

    pdf_url = None
    if uploaded_document is not None:
        try:
            pdf_url = await asyncio.to_thread(
                StorageService().generate_presigned_url,
                key=uploaded_document.file_path,
                expires_in=settings.statement_review_presign_expiry_seconds,
                public=True,
            )
        except StorageError as exc:
            logger.warning(
                "Could not generate presigned URL for review", error=str(exc), statement_id=str(statement_id)
            )

    validation_result = await validate_balance_chain(db, statement_id)
    reviewed_envelope = await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement.id)
    source_result = await get_current_statement_extraction_result(db, user_id=user_id, statement_id=statement.id)
    source_result_digest = source_result.content_digest if source_result is not None else None

    suggestions = await classification_suggestions(db, [t.id for t in transactions])
    base_response = compose_statement_response(statement, uploaded_document, transactions, suggestions=suggestions)

    return StatementReviewResponse(
        **base_response.model_dump(),
        stage1_status=statement.stage1_status,
        stage1_reviewed_at=statement.stage1_reviewed_at,
        manual_opening_balance=statement.manual_opening_balance,
        source_result_digest=source_result_digest,
        source_missing_facts=list(source_result.missing_required_facts) if source_result is not None else [],
        source_envelope_reviewable=supports_reviewed_statement_envelope(source_result)
        if source_result is not None
        else False,
        reviewed_envelope=_envelope_response(reviewed_envelope, source_result_digest or "")
        if reviewed_envelope is not None
        else None,
        pdf_url=pdf_url,
        balance_validation_result=BalanceValidationResult.model_validate(validation_result),
    )


@router.post("/{statement_id}/review/envelope", response_model=ReviewedStatementEnvelopeResponse)
async def confirm_statement_review_envelope(
    statement_id: UUID,
    request: ReviewedStatementEnvelopeRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReviewedStatementEnvelopeResponse:
    """Append a typed human confirmation over the statement's current source result."""
    try:
        envelope = await confirm_reviewed_statement_envelope(
            db,
            user_id=user_id,
            statement_id=statement_id,
            command=ReviewedStatementEnvelopeCommand(**request.model_dump()),
            trace_emitter=compose_statement_posting_dependencies().trace_emitter_factory(db),
        )
        await db.commit()
    except ReviewedStatementEnvelopeConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (TypeError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _envelope_response(envelope, request.source_result_digest)


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
        if request and request.account_id is not None:
            statement.account_id = request.account_id
            await db.flush()
            await resolve_statement_posting_account(db, statement, user_id)
        elif request and request.create_account_if_missing and not statement.account_id:
            await _create_statement_account_from_confirmation(db, statement, user_id)
        elif not statement.account_id:
            await resolve_statement_posting_account(db, statement, user_id)

        auto_filled = (
            await auto_fill_default_statement_dispositions(db, statement, user_id)
            if request and request.auto_fill_default_categories
            else 0
        )
        outcome = await approve_statement_workflow(
            db, statement_id, user_id, dependencies=compose_statement_posting_dependencies()
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    created_count = _posting_count_or_conflict(outcome) + auto_filled
    response = await _compose_statement_response(
        db, statement, user_id, transactions=getattr(statement, STATEMENT_RESOLVED_TRANSACTIONS_ATTR, None)
    )
    return Stage1ApprovalResponse(**response.model_dump(), journal_entries_created=created_count)


@router.post("/{statement_id}/review/reject", response_model=BankStatementResponse)
async def reject_statement_stage1(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    """Stage 1: Reject statement and enqueue reparse. The notes become the hint note of the rerun."""
    try:
        statement = await db.scalar(
            select(StatementSummary).where(StatementSummary.id == statement_id, StatementSummary.user_id == user_id)
        )
        if statement is None:
            raise ValueError("Statement not found or access denied")
        await _queue_statement_reparse(
            db,
            statement,
            user_id,
            hints=RunHints(note=decision.notes or None),
            allowed_statuses=_REJECT_STATUSES,
            while_pending=lambda: reject_statement_workflow(
                db,
                statement_id,
                user_id,
                reason=decision.notes,
                dependencies=compose_statement_posting_dependencies(),
                commit=False,
            ),
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except StorageError as exc:
        await db.rollback()
        raise_service_unavailable(f"Failed to fetch file from storage: {exc}", cause=exc)
    return await _compose_statement_response(db, await _get_statement_or_404(db, statement_id, user_id), user_id)


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
    return await _compose_statement_response(db, await _get_statement_or_404(db, statement_id, user_id), user_id)


async def wait_for_parse_tasks() -> None:
    """Wait for all pending background parsing tasks to complete."""
    if _PENDING_PARSE_TASKS:
        await asyncio.gather(*_PENDING_PARSE_TASKS, return_exceptions=True)
