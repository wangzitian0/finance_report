"""Statement extraction API router."""

import asyncio
import hashlib
import mimetypes
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, File, Form, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.composition import (
    auto_fill_default_statement_dispositions,
    compose_brokerage_import_service,
    compose_correction_callbacks,
    compose_statement_posting_dependencies,
    execute_statement_brokerage_import,
)
from src.config import settings
from src.deps import Ctx, ReadCtx
from src.extraction import (
    BROKERAGE_IMPORTABLE_STATUSES,
    DEFAULT_STALE_AFTER_DAYS,
    AtomicTransaction,
    BankStatementStatus,
    ClassificationStatus,
    CorrectionLoopService,
    ParseJob,
    RetireStatementCommand,
    ReviewedStatementEnvelopeCommand,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    StatementPostingOutcome,
    StatementPostingStatus,
    StatementRunRecord,
    StatementSummary,
    TransactionClassification,
    UploadedDocument,
    _brokerage_import_not_ready_reason,
    _brokerage_payload_from_persisted_extraction,
    _brokerage_payload_from_statement,
    approve_statement_workflow,
    classification_suggestions,
    confirm_reviewed_statement_envelope,
    create_run,
    create_statement_account_from_confirmation,
    current_reviewed_statement_envelope,
    effective_statement_transaction_filter,
    fail_run,
    find_statement_review_conflicts,
    get_account_statement_coverage,
    get_current_statement_extraction_result,
    list_runs,
    pending_stage1_review_filter,
    record_classification_feedback,
    record_correction,
    register_statement_source,
    reject_statement_workflow,
    resolve_statement_conflicts,
    resolve_statement_posting_account,
    resolve_statement_transactions,
    retire_statement,
    start_user_classify_run,
    start_user_extract_run,
    submit_classify_run,
    submit_parse_pipeline,
    supports_reviewed_statement_envelope,
    validate_balance_chain,
)
from src.ledger import Account
from src.llm import LitellmCatalog, Modality
from src.observability import ErrorIds, ensure_request_id, get_logger, safe_error_message
from src.platform import (
    BadGatewayError,
    ConflictError,
    ContentTooLargeError,
    DomainError,
    InternalServiceError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationFailedError,
)
from src.runtime import StorageError, StorageService
from src.schemas import (
    AccountCoverageListResponse,
    BankStatementListResponse,
    BankStatementResponse,
    StatementDecisionRequest,
    StatementRunListResponse,
    StatementRunRequest,
)
from src.schemas.extraction import (
    AiFeedbackRequest,
    AiFeedbackResponse,
    AiSuggestionListResponse,
    AiSuggestionResponse,
    BalanceValidationResult,
    CorrectionLoopReplayResponse,
    CorrectionRequest,
    CorrectionResponse,
    ResolveConflictsRequest,
    ReviewConflictCandidate,
    ReviewedStatementEnvelopeRequest,
    ReviewedStatementEnvelopeResponse,
    ReviewConflictsResolveResponse,
    ReviewConflictsResponse,
    Stage1ApprovalRequest,
    Stage1ApprovalResponse,
    StatementReviewResponse,
    compose_statement_list_item_response,
    compose_statement_response,
)
from src.schemas.portfolio import BrokerageImportResponse

router = APIRouter(prefix="/statements", tags=["statements"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = {"pdf", "csv", "png", "jpg", "jpeg"}
# A user can run the extraction again from these statuses.
_RERUN_STATUSES = frozenset({BankStatementStatus.PARSED, BankStatementStatus.REJECTED, BankStatementStatus.PARSING})
# A reject can start from these statuses. A retired or uploaded statement has no parse to run again.
_REJECT_STATUSES = _RERUN_STATUSES | {BankStatementStatus.APPROVED}
logger = get_logger(__name__)

_PENDING_PARSE_TASKS: set[asyncio.Task] = set()
_BROKERAGE_IMPORT_SERVICE = compose_brokerage_import_service()
_CORRECTION_LOOP = CorrectionLoopService()


def _txn_direction(txn: AtomicTransaction) -> Literal["IN", "OUT"] | None:
    val = txn.direction.value if hasattr(txn.direction, "value") else txn.direction
    if val == "IN":
        return "IN"
    if val == "OUT":
        return "OUT"
    return None


async def _count_classification_suggestions(db: AsyncSession, scope_filter: Any, filters: tuple[Any, ...]) -> int:
    stmt = (
        select(func.count(TransactionClassification.id))
        .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
        .where(scope_filter, *filters)
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


def _track_task(task: asyncio.Task) -> None:
    _PENDING_PARSE_TASKS.add(task)
    task.add_done_callback(_PENDING_PARSE_TASKS.discard)


def _posting_count_or_conflict(outcome: StatementPostingOutcome) -> int:
    if outcome.status is StatementPostingStatus.REVIEW_REQUIRED:
        raise ConflictError(f"Economic review required: {', '.join(outcome.review_reasons)}")
    return outcome.created_count


async def _validate_vision_model(model: str | None) -> None:
    if not model:
        return
    spec = await LitellmCatalog().get(model)
    if spec is None:
        raise ValidationFailedError("Invalid model selection. Choose a model from /llm/catalog.")
    if not spec.accepts(Modality.IMAGE):
        raise ValidationFailedError("Selected model does not support image/PDF inputs.")


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
    db: AsyncSession, statement: StatementSummary, user_id: UUID
) -> BankStatementResponse:
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    transactions = await resolve_statement_transactions(db, statement)
    suggestions = await classification_suggestions(db, [t.id for t in transactions])
    return compose_statement_response(statement, uploaded_document, transactions, suggestions=suggestions)


def _approval_response(statement: StatementSummary, created_count: int) -> Stage1ApprovalResponse:
    return Stage1ApprovalResponse(
        id=statement.id,
        account_id=statement.account_id,
        status=statement.status,
        validation_error=statement.validation_error,
        journal_entries_created=created_count,
    )


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
        raise ResourceNotFoundError("Statement not found")
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
    db: AsyncSession,
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


async def _queue_classify_run(db: AsyncSession, statement_id: UUID, user_id: UUID, hints: RunHints) -> UUID:
    """Start a user classify run, commit it, then run it as a task of this process."""
    run_id = await start_user_classify_run(db, statement_id=statement_id, user_id=user_id, hints=hints)
    await db.commit()
    try:
        _track_task(submit_classify_run(run_id, db=db))
    except Exception as exc:  # noqa: BLE001 - a run that no task owns would stay requested until the reaper
        await fail_run(db, run_id, error_code="dispatch_failed", error_message="The run could not start.")
        await db.commit()
        raise ServiceUnavailableError("The classification could not start. Try again.") from exc
    return run_id


def build_statement_storage_key(*, statement_id: UUID, file_hash: str, extension: str) -> str:
    safe_extension = extension.lower() if extension.lower() in _ALLOWED_EXTENSIONS else "bin"
    return f"statements/{statement_id}/{file_hash[:16]}.{safe_extension}"


@router.post("", response_model=BankStatementResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_statement(
    file: UploadFile = File(...),
    institution: Annotated[str | None, Form()] = None,
    account_id: Annotated[UUID | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
    *,
    ctx: Ctx,
) -> BankStatementResponse:
    """Upload a financial statement and enqueue parsing."""
    db, user_id = ctx.db, ctx.user_id
    filename = Path(file.filename or "unknown").name or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    if extension not in _ALLOWED_EXTENSIONS:
        raise ValidationFailedError(f"Unsupported file type: {extension}")

    institution = institution.strip() if institution else None
    if extension == "csv" and not institution:
        raise ValidationFailedError("Institution is required for CSV uploads. Please select an institution and retry.")

    if account_id is not None:
        if (
            await db.execute(select(Account.id).where(Account.id == account_id, Account.user_id == user_id))
        ).scalar_one_or_none() is None:
            raise ResourceNotFoundError("Account not found")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ContentTooLargeError("File exceeds 10MB limit")

    file_hash = hashlib.sha256(content).hexdigest()
    if (
        await db.execute(
            select(StatementSummary.id).where(
                StatementSummary.user_id == user_id, StatementSummary.file_hash == file_hash
            )
        )
    ).scalar_one_or_none():
        raise ConflictError("Duplicate statement upload")

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
        raise ServiceUnavailableError(str(exc)) from exc

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
        if isinstance(exc, DomainError):
            raise
        raise InternalServiceError("Failed to persist statement metadata") from exc

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
    ctx: Ctx,
) -> StatementRunRecord:
    """Run the extraction or the classification of a statement again, with optional hints.

    The actor of the run is the authenticated user. An active run gives 409 with `active_run_id`. A classify run
    needs a parsed statement, takes the hints for every file type, and runs as a task of this process.
    """
    db, user_id = ctx.db, ctx.user_id
    statement = await _get_statement_or_404(db, statement_id, user_id)
    if request.kind == "classify":
        if statement.status is not BankStatementStatus.PARSED:
            raise ValidationFailedError("Can only classify again for a parsed statement")
        run_id = await _queue_classify_run(db, statement_id, user_id, request.hints)
        return next(run for run in await list_runs(db, statement_id, user_id) if run.id == run_id)
    if statement.status not in _RERUN_STATUSES:
        raise ValidationFailedError("Can only run again for parsed, rejected, or stuck parsing statements")
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
        raise ServiceUnavailableError(f"Failed to fetch file from storage: {exc}") from exc
    runs = await list_runs(db, statement_id, user_id)
    return next(run for run in runs if run.id == run_id)


@router.get("/{statement_id}/runs", response_model=StatementRunListResponse)
async def list_statement_runs(statement_id: UUID, ctx: ReadCtx) -> StatementRunListResponse:
    """List the runs of a statement by attempt number, with their hints, actor, state and error."""
    await _get_statement_or_404(ctx.db, statement_id, ctx.user_id)
    runs = await list_runs(ctx.db, statement_id, ctx.user_id)
    return StatementRunListResponse(items=runs, total=len(runs))


@router.get("", response_model=BankStatementListResponse)
async def list_statements(ctx: ReadCtx) -> BankStatementListResponse:
    """List non-retired statements for the current user."""
    return await _list_statements_by_where(
        ctx.db,
        ctx.user_id,
        StatementSummary.user_id == ctx.user_id,
        StatementSummary.status != BankStatementStatus.RETIRED,
    )


@router.get("/pending-review", response_model=BankStatementListResponse)
async def list_pending_review(ctx: ReadCtx) -> BankStatementListResponse:
    """List statements pending Stage 1 human review."""
    return await _list_statements_by_where(
        ctx.db,
        ctx.user_id,
        StatementSummary.user_id == ctx.user_id,
        StatementSummary.status == BankStatementStatus.PARSED,
        pending_stage1_review_filter(),
    )


@router.get("/coverage", response_model=AccountCoverageListResponse)
async def list_statement_coverage(
    ctx: ReadCtx,
    as_of: date | None = Query(None, description="Date used for stale-account evaluation"),
    stale_after_days: int = Query(
        DEFAULT_STALE_AFTER_DAYS,
        ge=1,
        le=366,
        description="Number of days after latest confirmed source date before an account is stale",
    ),
) -> AccountCoverageListResponse:
    """List statement coverage status for active accounts."""
    return await get_account_statement_coverage(
        ctx.db,
        ctx.user_id,
        as_of=as_of,
        stale_after_days=stale_after_days,
    )


@router.get("/classification-suggestions", response_model=AiSuggestionListResponse)
async def list_classification_suggestions(
    ctx: ReadCtx,
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum items to return")] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    statement_id: Annotated[UUID | None, Query(description="Optional statement ID filter")] = None,
) -> AiSuggestionListResponse:
    """List pending AI classification suggestions in the 60-84 review band."""
    db, user_id = ctx.db, ctx.user_id
    scope_filter = (
        effective_statement_transaction_filter(user_id, statement_id)
        if statement_id is not None
        else (AtomicTransaction.user_id == user_id)
    )
    cls_filters = (
        TransactionClassification.status == ClassificationStatus.DRAFT,
        TransactionClassification.confidence_score >= 60,
        TransactionClassification.confidence_score < 85,
        func.coalesce(TransactionClassification.tags["corrected_by_user"].astext, "false") != "true",
    )
    total = await _count_classification_suggestions(db, scope_filter, cls_filters)
    rows = (
        await db.execute(
            select(TransactionClassification, AtomicTransaction)
            .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
            .where(scope_filter, *cls_filters)
            .order_by(TransactionClassification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items: list[AiSuggestionResponse] = []
    for cls, txn in rows:
        raw_cat = cls.tags.get("category") if isinstance(cls.tags, dict) else None
        suggested = (
            raw_cat
            if isinstance(raw_cat, str) and raw_cat
            else (str(cls.account_id) if cls.account_id else "AI classification")
        )
        items.append(
            AiSuggestionResponse(
                suggestion_id=cls.id,
                transaction=txn.description,
                suggested_category_or_match=suggested,
                ai_score=cls.confidence_score or 60,
                ai_reasoning="Pending AI classification suggestion requires human review.",
                direction=_txn_direction(txn),
            )
        )
    return AiSuggestionListResponse(items=items, total=total)


@router.post("/classification-feedback", response_model=AiFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_classification_feedback(
    payload: AiFeedbackRequest,
    ctx: Ctx,
) -> AiFeedbackResponse:
    """Persist user feedback for a classification suggestion and apply it to the draft."""
    db, user_id = ctx.db, ctx.user_id
    recorded = await record_classification_feedback(
        db,
        user_id=user_id,
        suggestion_id=payload.suggestion_id,
        action=payload.action,
        corrected_value=payload.corrected_value,
    )
    if recorded is None:
        raise ResourceNotFoundError("Classification suggestion not found")
    feedback, effect = recorded
    await db.flush()
    await db.refresh(feedback)
    response = AiFeedbackResponse.model_validate(feedback)
    response.effect = effect
    return response


@router.post("/corrections", response_model=CorrectionResponse, status_code=status.HTTP_201_CREATED)
async def create_correction(
    body: CorrectionRequest,
    *,
    ctx: Ctx,
) -> CorrectionResponse:
    """Record a user correction to an AI-suggested category."""
    db, user_id = ctx.db, ctx.user_id
    correction = await record_correction(
        db,
        user_id=user_id,
        transaction_id=body.transaction_id,
        corrected_category=body.corrected_category,
        corrected_account_id=body.corrected_account_id,
        **compose_correction_callbacks(),
    )
    await db.flush()
    return CorrectionResponse(
        id=correction.id,
        transaction_id=correction.transaction_id,
        original_category=correction.original_category,
        corrected_category=correction.corrected_category,
    )


@router.get("/correction-loop/replay", response_model=CorrectionLoopReplayResponse)
async def get_correction_loop_replay(ctx: ReadCtx) -> CorrectionLoopReplayResponse:
    """Surface the held-out replay of the live correction corpus."""
    result = await _CORRECTION_LOOP.replay(ctx.db, ctx.user_id)
    return CorrectionLoopReplayResponse(
        holdout_size=result.holdout_size,
        grounded=result.grounded,
        proportion_before=result.proportion_before,
        proportion_after=result.proportion_after,
        reduced=result.reduced,
        high_confidence_count=result.high_confidence_count,
        medium_confidence_count=result.medium_confidence_count,
        low_confidence_count=result.low_confidence_count,
        low_confidence_proportion=result.low_confidence_proportion,
    )


@router.get("/{statement_id}", response_model=BankStatementResponse)
async def get_statement(statement_id: UUID, ctx: ReadCtx) -> BankStatementResponse:
    """Get a statement with all its transactions."""
    return await _compose_statement_response(
        ctx.db, await _get_statement_or_404(ctx.db, statement_id, ctx.user_id), ctx.user_id
    )


@router.get(
    "/{statement_id}/document",
    responses={
        200: {
            "description": "Original uploaded statement document bytes.",
            "content": {"application/pdf": {}, "text/csv": {}, "image/png": {}, "image/jpeg": {}},
        }
    },
)
async def get_statement_document(statement_id: UUID, ctx: ReadCtx) -> Response:
    """Stream the original uploaded document for a statement, same-origin."""
    db, user_id = ctx.db, ctx.user_id
    statement = await _get_statement_or_404(db, statement_id, user_id)
    uploaded_document = await _resolve_uploaded_document(db, statement, user_id)
    if uploaded_document is None:
        raise ResourceNotFoundError("No uploaded document is associated with this statement")
    try:
        content = await asyncio.to_thread(StorageService().get_object, uploaded_document.file_path)
    except StorageError as exc:
        logger.warning("Could not fetch statement document", error=str(exc), statement_id=str(statement_id))
        raise BadGatewayError("Statement document is temporarily unavailable") from exc
    media_type = mimetypes.guess_type(uploaded_document.original_filename)[0] or "application/pdf"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/{statement_id}/brokerage-imports",
    response_model=BrokerageImportResponse,
    status_code=status.HTTP_200_OK,
)
async def import_brokerage_statement_positions(
    statement_id: UUID, ctx: Ctx
) -> BrokerageImportResponse:
    """Import portfolio positions from a parsed brokerage statement."""
    db, user_id = ctx.db, ctx.user_id
    statement = await _get_statement_or_404(db, statement_id, user_id)
    transactions = await resolve_statement_transactions(db, statement)
    if statement.status not in BROKERAGE_IMPORTABLE_STATUSES:
        raise ValidationFailedError(_brokerage_import_not_ready_reason(statement, len(transactions)))

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
    import_result = await execute_statement_brokerage_import(
        db,
        statement=statement,
        user_id=user_id,
        payload=payload,
        source_filename=source_filename,
        source_document_id=source_document_id,
        request_id=request_id,
        import_service=_BROKERAGE_IMPORT_SERVICE,
        audit_logger=logger,
    )

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
async def delete_statement(statement_id: UUID, ctx: Ctx) -> None:
    """Retire a statement from product views while retaining source history."""
    await retire_statement(
        ctx.db,
        RetireStatementCommand(statement_id=statement_id, user_id=ctx.user_id),
        base_currency=await ctx.get_base_currency(),
        dependencies=compose_statement_posting_dependencies(),
    )
    await ctx.db.flush()


@router.get("/{statement_id}/review", response_model=StatementReviewResponse)
async def get_statement_for_review(statement_id: UUID, ctx: ReadCtx) -> StatementReviewResponse:
    """Get Stage 1 review data for a statement."""
    db, user_id = ctx.db, ctx.user_id
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


@router.post("/{statement_id}/review-envelopes", response_model=ReviewedStatementEnvelopeResponse)
async def confirm_statement_review_envelope(
    statement_id: UUID,
    request: ReviewedStatementEnvelopeRequest,
    ctx: Ctx,
) -> ReviewedStatementEnvelopeResponse:
    """Append a typed human confirmation over the statement's current source result."""
    db, user_id = ctx.db, ctx.user_id
    envelope = await confirm_reviewed_statement_envelope(
        db,
        user_id=user_id,
        statement_id=statement_id,
        command=ReviewedStatementEnvelopeCommand(**request.model_dump()),
        trace_emitter=compose_statement_posting_dependencies().trace_emitter_factory(db),
    )
    await db.flush()
    return _envelope_response(envelope, request.source_result_digest)


@router.post("/{statement_id}/approvals", response_model=Stage1ApprovalResponse)
async def approve_statement_stage1(
    statement_id: UUID,
    ctx: Ctx,
    request: Annotated[Stage1ApprovalRequest | None, Body()] = None,
) -> Stage1ApprovalResponse:
    """Stage 1: Approve statement with balance validation."""
    db, user_id = ctx.db, ctx.user_id
    statement = await _get_statement_or_404(db, statement_id, user_id)
    preloaded_account: Account | None = None
    if request and request.account_id is not None:
        statement.account_id = request.account_id
        await db.flush()
        preloaded_account = await resolve_statement_posting_account(db, statement, user_id)
    elif request and request.create_account_if_missing and not statement.account_id:
        preloaded_account = await create_statement_account_from_confirmation(db, statement, user_id)
    elif not statement.account_id:
        preloaded_account = await resolve_statement_posting_account(db, statement, user_id)
    auto_filled = (
        await auto_fill_default_statement_dispositions(db, statement, user_id)
        if request and request.auto_fill_default_categories
        else 0
    )
    outcome = await approve_statement_workflow(
        db,
        statement_id,
        user_id,
        dependencies=compose_statement_posting_dependencies(),
        preloaded_bank_account=preloaded_account,
        base_currency=await ctx.get_base_currency(),
    )

    created_count = _posting_count_or_conflict(outcome) + auto_filled
    return _approval_response(statement, created_count)


@router.post("/{statement_id}/rejections", response_model=BankStatementResponse)
async def reject_statement_stage1(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    ctx: Ctx,
) -> BankStatementResponse:
    """Stage 1: Reject statement and enqueue reparse. The notes become the hint note of the rerun."""
    db, user_id = ctx.db, ctx.user_id
    statement = await _get_statement_or_404(db, statement_id, user_id)
    base_currency = await ctx.get_base_currency()
    try:
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
                base_currency=base_currency,
            ),
        )
    except StorageError as exc:
        raise ServiceUnavailableError(f"Failed to fetch file from storage: {exc}") from exc
    return await _compose_statement_response(db, await _get_statement_or_404(db, statement_id, user_id), user_id)


@router.get("/{statement_id}/conflicts", response_model=ReviewConflictsResponse)
async def get_review_conflicts(
    statement_id: UUID, ctx: ReadCtx
) -> ReviewConflictsResponse:
    """Return duplicate and transfer-pair candidates for a statement."""
    db, user_id = ctx.db, ctx.user_id
    statement = await _get_statement_or_404(db, statement_id, user_id)
    transactions = await resolve_statement_transactions(db, statement)

    def _candidate(txn: AtomicTransaction) -> ReviewConflictCandidate:
        return ReviewConflictCandidate(
            id=txn.id,
            txn_date=txn.txn_date,
            description=txn.description,
            amount=txn.amount,
            direction=txn.direction.value if hasattr(txn.direction, "value") else str(txn.direction),
        )

    duplicates, transfer_pairs = find_statement_review_conflicts(transactions)
    return ReviewConflictsResponse(
        duplicates=[_candidate(txn) for txn in duplicates],
        transfer_pairs=[_candidate(txn) for txn in transfer_pairs],
        resolved=statement.stage1_conflicts_resolved_at is not None,
    )


@router.post("/{statement_id}/conflict-resolutions", response_model=ReviewConflictsResolveResponse)
async def resolve_review_conflicts(
    statement_id: UUID,
    request: ResolveConflictsRequest,
    ctx: Ctx,
) -> ReviewConflictsResolveResponse:
    """Resolve Stage-1 duplicate/transfer-pair candidates (#962)."""
    db, user_id = ctx.db, ctx.user_id
    statement = await resolve_statement_conflicts(db, statement_id, user_id)
    resolved_at = statement.stage1_conflicts_resolved_at
    await db.flush()

    logger.info(
        "stage1.conflicts.resolved",
        audit_event="stage1.conflicts.resolved",
        statement_id=str(statement_id),
        action=request.action,
        note=request.note,
    )
    return ReviewConflictsResolveResponse(resolved=True, resolved_at=resolved_at)


async def wait_for_parse_tasks() -> None:
    """Wait for all pending background parsing tasks to complete."""
    if _PENDING_PARSE_TASKS:
        await asyncio.gather(*_PENDING_PARSE_TASKS, return_exceptions=True)
