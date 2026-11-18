"""Reconciliation API router."""

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from src.composition import compose_reviewed_disposition_dependencies
from src.deps import Ctx, Pagination, ReadCtx
from src.extraction import (
    AtomicTransaction,
    BankStatementStatus,
    StatementSummary,
    effective_statement_transaction_filter,
)
from src.ledger import Account, JournalEntry
from src.observability import ensure_request_id, get_logger, log_financial_mutation, safe_error_message
from src.platform import ResourceNotFoundError, get_owned_or_raise, paginate
from src.reconciliation import (
    CheckStatus,
    CheckType,
    ReconciliationMatch,
    ReconciliationStatus,
    ReviewedDispositionCommand,
    accept_match as accept_match_service,
    apply_reconciliation_adjustment,
    batch_decide_matches,
    count_pending_review_items,
    derive_reconciliation_score_tier,
    detect_anomalies,
    entry_total_amount,
    execute_matching,
    get_pending_items,
    get_processing_transfer_summary,
    get_reconciliation_stats,
    get_stage2_queue,
    list_checks,
    list_pending_processing_transfers,
    parse_check_resolution_action,
    posted_statement_source_ids,
    reject_match as reject_match_service,
    resolve_check,
    run_all_consistency_checks,
    submit_reviewed_disposition,
)
from src.schemas.reconciliation import (
    AnomalyResponse,
    BankTransactionSummary,
    ConsistencyCheckListResponse,
    ConsistencyCheckResponse,
    ConsistencyCheckRunRequest,
    JournalEntrySummary,
    ProcessingPendingItem,
    ProcessingPendingListResponse,
    ProcessingSummaryResponse,
    ReconciliationAdjustmentRequest,
    ReconciliationAdjustmentResponse,
    ReconciliationMatchBatchRequest,
    ReconciliationMatchBatchResponse,
    ReconciliationMatchDecisionRequest,
    ReconciliationMatchListResponse,
    ReconciliationMatchResponse,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
    ReconciliationStatsResponse,
    ReconciliationStatusEnum,
    ResolveCheckRequest,
    ReviewedDispositionRequest,
    Stage2PendingMatch,
    Stage2ReviewQueueResponse,
    UnmatchedTransactionsResponse,
)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])
logger = get_logger(__name__)


def _unmatched_atomic_txn_query(user_id: UUID, *, include_pending_stage1: bool = False):
    matched_txn = aliased(AtomicTransaction)
    matched_subquery = (
        select(ReconciliationMatch.atomic_txn_id)
        .join(matched_txn, matched_txn.id == ReconciliationMatch.atomic_txn_id)
        .where(
            matched_txn.user_id == user_id,
            ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)),
            ReconciliationMatch.superseded_by_id.is_(None),
            ReconciliationMatch.atomic_txn_id.is_not(None),
        )
    )
    return select(AtomicTransaction).where(
        effective_statement_transaction_filter(user_id, include_pending_stage1=include_pending_stage1),
        AtomicTransaction.id.notin_(matched_subquery),
        AtomicTransaction.id.notin_(posted_statement_source_ids(user_id)),
    )


def _statement_atomic_txn_ids_query(statement: StatementSummary) -> Select[tuple[UUID]]:
    return select(AtomicTransaction.id).where(effective_statement_transaction_filter(statement.user_id, statement.id))


def _build_entry_summary(entry: JournalEntry) -> JournalEntrySummary:
    lines = getattr(entry, "lines", None)
    return JournalEntrySummary(
        id=entry.id,
        entry_date=entry.entry_date,
        memo=entry.memo,
        status=entry.status.value,
        total_amount=entry_total_amount(entry, currency=lines[0].currency if lines else "SGD"),
    )


async def _load_entry_summaries(
    db: AsyncSession, matches: Sequence[ReconciliationMatch], user_id: UUID
) -> dict[str, JournalEntrySummary]:
    if not matches:
        return {}
    entry_ids: set[UUID] = set()
    for match in matches:
        for eid in match.journal_entry_ids or []:
            try:
                entry_ids.add(UUID(eid))
            except ValueError:
                logger.warning("Invalid UUID in journal_entry_ids", match_id=str(match.id), invalid_entry_id=eid)
    if not entry_ids:
        return {}
    return {
        str(e.id): _build_entry_summary(e)
        for e in (
            await db.execute(
                select(JournalEntry)
                .where(JournalEntry.id.in_(entry_ids), JournalEntry.user_id == user_id)
                .options(selectinload(JournalEntry.lines))
            )
        )
        .scalars()
        .all()
    }


async def _load_transactions(
    db: AsyncSession, matches: Sequence[ReconciliationMatch], user_id: UUID | None = None
) -> dict[UUID, AtomicTransaction]:
    if not matches:
        return {}
    txn_ids = {m.atomic_txn_id for m in matches}
    stmt = select(AtomicTransaction).where(AtomicTransaction.id.in_(txn_ids))
    if user_id is not None:
        stmt = stmt.where(AtomicTransaction.user_id == user_id)
    return {t.id: t for t in (await db.execute(stmt)).scalars().all()}


def _build_match_response(
    match: ReconciliationMatch,
    *,
    transaction: AtomicTransaction | None = None,
    entry_summaries: dict[str, JournalEntrySummary] | None = None,
) -> ReconciliationMatchResponse:
    summaries = entry_summaries or {}
    return ReconciliationMatchResponse(
        id=match.id,
        atomic_txn_id=match.atomic_txn_id,
        journal_entry_ids=match.journal_entry_ids,
        match_score=match.match_score,
        score_breakdown=match.score_breakdown,
        status=ReconciliationStatusEnum(match.status.value),
        version=match.version,
        superseded_by_id=match.superseded_by_id,
        created_at=match.created_at,
        updated_at=match.updated_at,
        transaction=BankTransactionSummary.model_validate(transaction) if transaction else None,
        entries=[s for eid in (match.journal_entry_ids or []) if (s := summaries.get(eid)) is not None],
    )


async def _load_match_responses(
    db: AsyncSession, matches: Sequence[ReconciliationMatch], user_id: UUID
) -> list[ReconciliationMatchResponse]:
    if not matches:
        return []
    entry_summaries = await _load_entry_summaries(db, matches, user_id)
    txn_map = await _load_transactions(db, matches, user_id)
    return [
        _build_match_response(m, transaction=txn_map.get(m.atomic_txn_id), entry_summaries=entry_summaries)
        for m in matches
    ]


@router.post("/runs", response_model=ReconciliationRunResponse, status_code=status.HTTP_200_OK)
async def run_reconciliation(
    payload: ReconciliationRunRequest,
    *,
    ctx: Ctx,
) -> ReconciliationRunResponse:
    """Run the reconciliation pipeline for the current user."""
    db, user_id = ctx.db, ctx.user_id
    statement: StatementSummary | None = None
    if payload.statement_id:
        statement = (
            await db.execute(
                select(StatementSummary).where(
                    StatementSummary.id == payload.statement_id,
                    StatementSummary.user_id == user_id,
                    StatementSummary.status != BankStatementStatus.RETIRED,
                )
            )
        ).scalar_one_or_none()
        if statement is None:
            raise ResourceNotFoundError("Statement not found")

    request_id = ensure_request_id()
    statement_id = str(payload.statement_id) if payload.statement_id else None
    logger.info(
        "reconciliation.run.started",
        audit_event="reconciliation.run.started",
        request_id=request_id,
        statement_id=statement_id,
        phase="matching_started",
        progress=None,
        model_to_use=None,
        limit=payload.limit,
    )
    try:
        currency = await ctx.get_base_currency()
        matches = await execute_matching(db, limit=payload.limit, user_id=user_id, currency=currency)
    except Exception as exc:
        logger.exception(
            "reconciliation.run.failed",
            audit_event="reconciliation.run.failed",
            request_id=request_id,
            statement_id=statement_id,
            phase="matching_failed",
            progress=None,
            model_to_use=None,
            limit=payload.limit,
            error_type=type(exc).__name__,
            safe_error_message=safe_error_message(str(exc)),
        )
        raise

    auto_accepted = sum(1 for m in matches if m.status.value == "auto_accepted")
    pending_review = sum(1 for m in matches if m.status.value == "pending_review")

    unmatched_query = _unmatched_atomic_txn_query(user_id, include_pending_stage1=statement is not None)
    if statement is not None:
        unmatched_query = unmatched_query.where(AtomicTransaction.id.in_(_statement_atomic_txn_ids_query(statement)))
    unmatched_count = (await db.execute(select(func.count()).select_from(unmatched_query.subquery()))).scalar_one()

    logger.info(
        "reconciliation.run.completed",
        audit_event="reconciliation.run.completed",
        request_id=request_id,
        statement_id=statement_id,
        phase="matching_completed",
        progress=None,
        model_to_use=None,
        limit=payload.limit,
        matches_created=len(matches),
        auto_accepted=auto_accepted,
        pending_review=pending_review,
        unmatched=unmatched_count,
    )
    return ReconciliationRunResponse(
        matches_created=len(matches),
        auto_accepted=auto_accepted,
        pending_review=pending_review,
        unmatched=unmatched_count,
    )


@router.get("/matches", response_model=ReconciliationMatchListResponse)
async def list_matches(
    status_filter: ReconciliationStatusEnum | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    ctx: ReadCtx,
) -> ReconciliationMatchListResponse:
    """Return reconciliation matches for the current user."""
    db, user_id = ctx.db, ctx.user_id
    clauses = [AtomicTransaction.user_id == user_id]
    if status_filter:
        clauses.append(ReconciliationMatch.status == ReconciliationStatus(status_filter.value))
    query = (
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(*clauses)
    )
    matches, total = await paginate(
        db, query, limit=limit, offset=offset, order_by=(ReconciliationMatch.created_at.desc(),)
    )
    return ReconciliationMatchListResponse(items=await _load_match_responses(db, matches, user_id), total=total)


@router.get("/pending", response_model=ReconciliationMatchListResponse)
async def pending_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    ctx: ReadCtx,
) -> ReconciliationMatchListResponse:
    """Return the Stage-2 pending review queue."""
    db, user_id = ctx.db, ctx.user_id
    matches = await get_pending_items(db, limit=limit, offset=offset, user_id=user_id)
    total = await count_pending_review_items(db, user_id=user_id)
    return ReconciliationMatchListResponse(items=await _load_match_responses(db, matches, user_id), total=total)


@router.patch("/matches/{match_id}", response_model=ReconciliationMatchResponse)
async def update_match_decision(
    match_id: UUID,
    payload: ReconciliationMatchDecisionRequest,
    *,
    ctx: Ctx,
) -> ReconciliationMatchResponse:
    """Accept or reject one reconciliation match."""
    db, user_id = ctx.db, ctx.user_id
    if payload.action == "accept":
        match = await accept_match_service(db, match_id, user_id=user_id)
    else:
        match = await reject_match_service(db, match_id, user_id=user_id)
    await db.flush()
    if payload.action == "accept":
        log_financial_mutation(
            logger,
            "reconciliation.match.accepted",
            user_id=user_id,
            action="accept",
            resource_type="reconciliation_match",
            resource_id=match.id,
            status=match.status.value,
        )
    return (await _load_match_responses(db, [match], user_id))[0]


@router.post("/matches", response_model=ReconciliationMatchBatchResponse)
async def batch_update_matches(
    payload: ReconciliationMatchBatchRequest, *, ctx: Ctx
) -> ReconciliationMatchBatchResponse:
    """Apply a batch accept or reject decision to pending reconciliation matches."""
    db, user_id = ctx.db, ctx.user_id
    result = await batch_decide_matches(
        db,
        user_id=user_id,
        action=payload.action,
        match_ids=payload.match_ids,
        run_id=payload.run_id,
        min_score=payload.min_score,
    )

    if payload.match_ids:
        await db.flush()
        if payload.action == "accept":
            log_financial_mutation(
                logger,
                "reconciliation.match.batch_accepted",
                user_id=user_id,
                action="batch_accept",
                resource_type="reconciliation_match",
                resource_id="batch",
                requested_count=len(payload.match_ids),
                accepted_count=result.approved_count,
            )
        else:
            log_financial_mutation(
                logger,
                "reconciliation.match.batch_rejected",
                user_id=user_id,
                action="batch_reject",
                resource_type="reconciliation_match",
                resource_id="batch",
                requested_count=len(payload.match_ids),
                rejected_count=result.rejected_count,
            )
    return ReconciliationMatchBatchResponse(
        approved_count=result.approved_count,
        rejected_count=result.rejected_count,
        journal_entries_reconciled=result.journal_entries_reconciled,
    )


@router.get("/stats", response_model=ReconciliationStatsResponse)
async def reconciliation_stats(*, ctx: ReadCtx) -> ReconciliationStatsResponse:
    """Return reconciliation statistics."""
    stats = await get_reconciliation_stats(ctx.db, ctx.user_id, include_distribution=True)
    return ReconciliationStatsResponse(
        total_transactions=stats.total_transactions,
        matched_transactions=stats.matched_transactions,
        unmatched_transactions=stats.unmatched_transactions,
        pending_review=stats.pending_review,
        auto_accepted=stats.auto_accepted,
        match_rate=stats.match_rate,
        score_distribution=stats.score_distribution or {},
    )


@router.get("/unmatched", response_model=UnmatchedTransactionsResponse)
async def list_unmatched(
    statement_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    *,
    ctx: ReadCtx,
) -> UnmatchedTransactionsResponse:
    """Return unmatched transactions."""
    db, user_id = ctx.db, ctx.user_id
    query = _unmatched_atomic_txn_query(user_id, include_pending_stage1=statement_id is not None)
    if statement_id is not None:
        statement = await get_owned_or_raise(db, StatementSummary, statement_id, user_id, name="Statement")
        query = query.where(AtomicTransaction.id.in_(_statement_atomic_txn_ids_query(statement)))
    rows, total = await paginate(
        db, query, limit=limit, offset=offset, order_by=(AtomicTransaction.txn_date.desc(),)
    )
    return UnmatchedTransactionsResponse(items=[BankTransactionSummary.model_validate(r) for r in rows], total=total)


@router.post("/unmatched/{txn_id}/reviewed-dispositions", response_model=JournalEntrySummary)
async def submit_unmatched_reviewed_disposition(
    txn_id: UUID,
    payload: ReviewedDispositionRequest,
    *,
    ctx: Ctx,
) -> JournalEntrySummary:
    """Post one unmatched source transaction from explicit reviewed economic meaning."""
    db, user_id = ctx.db, ctx.user_id
    entry = await submit_reviewed_disposition(
        db,
        transaction_id=txn_id,
        user_id=user_id,
        command=ReviewedDispositionCommand(
            intent=payload.intent,
            counter_account_id=payload.counter_account_id,
            category=payload.category,
            rationale=payload.rationale,
        ),
        dependencies=compose_reviewed_disposition_dependencies(db),
        base_currency=await ctx.get_base_currency(),
    )
    entry_with_lines = (
        await db.execute(
            select(JournalEntry).options(selectinload(JournalEntry.lines)).where(JournalEntry.id == entry.id)
        )
    ).scalar_one()
    response = _build_entry_summary(entry_with_lines)
    await db.flush()
    return response


@router.get("/transactions/{txn_id}/anomalies", response_model=list[AnomalyResponse])
async def list_anomalies(
    txn_id: UUID, *, ctx: ReadCtx, pagination: Pagination
) -> list[AnomalyResponse]:
    """Return reconciliation anomalies."""
    db, user_id = ctx.db, ctx.user_id
    txn = await get_owned_or_raise(db, AtomicTransaction, txn_id, user_id, name="Transaction")
    anomalies = await detect_anomalies(db, txn, user_id=user_id)
    return [AnomalyResponse(**a.__dict__) for a in anomalies[pagination.offset : pagination.offset + pagination.limit]]


@router.post("/adjustments", response_model=ReconciliationAdjustmentResponse, status_code=status.HTTP_200_OK)
async def post_reconciliation_adjustment(
    payload: ReconciliationAdjustmentRequest, *, ctx: Ctx
) -> ReconciliationAdjustmentResponse:
    """Post an immaterial penny rounding adjustment."""
    db, user_id = ctx.db, ctx.user_id
    account = await get_owned_or_raise(db, Account, payload.account_id, user_id, name="Account")
    base_currency = await ctx.get_base_currency()
    result = await apply_reconciliation_adjustment(
        db,
        account=account,
        base_currency=base_currency,
        bank_balance=payload.bank_balance,
        book_balance=payload.book_balance,
        threshold=payload.threshold,
        fx_rate=payload.fx_rate,
        entry_date=payload.entry_date,
    )
    if result.entry is not None:
        await db.refresh(result.entry, ["lines"])
    await db.flush()

    if result.entry is not None:
        log_financial_mutation(
            logger,
            "reconciliation.adjustment.posted",
            user_id=user_id,
            action="adjustment",
            resource_type="journal_entry",
            resource_id=result.entry.id,
            difference=str(result.difference),
        )
    return ReconciliationAdjustmentResponse(
        account_id=result.account_id,
        bank_balance=result.bank_balance,
        book_balance=result.book_balance,
        difference=result.difference,
        is_gain=result.is_gain,
        journal_entry_id=result.journal_entry_id,
        entry=_build_entry_summary(result.entry) if result.entry is not None else None,
    )


@router.get("/transfers/summary", response_model=ProcessingSummaryResponse)
async def get_processing_summary(
    ctx: ReadCtx,
) -> ProcessingSummaryResponse:
    """Return the processing-account in-transit transfer summary."""
    default_currency = await ctx.get_base_currency()
    summary = await get_processing_transfer_summary(ctx.db, ctx.user_id, default_currency=default_currency)
    return ProcessingSummaryResponse(
        pending_count=summary.pending_count,
        pending_total=summary.pending_total,
        current_balance=summary.current_balance,
        currency=summary.currency,
        oldest_pending_date=summary.oldest_pending_date,
    )


@router.get("/transfers/pending", response_model=ProcessingPendingListResponse)
async def list_processing_pending(
    ctx: ReadCtx,
) -> ProcessingPendingListResponse:
    """Return pending unpaired transfer legs in the processing pipeline."""
    default_currency = await ctx.get_base_currency()
    legs = await list_pending_processing_transfers(ctx.db, ctx.user_id, default_currency=default_currency)
    items = [ProcessingPendingItem(**leg) for leg in legs]
    return ProcessingPendingListResponse(items=items, total=len(items))


@router.get("/review-queue", response_model=Stage2ReviewQueueResponse)
async def get_stage2_review_queue(
    ctx: ReadCtx, run_id: str | None = None
) -> Stage2ReviewQueueResponse:
    """Return the Stage-2 review queue (pending matches + consistency checks)."""
    db, user_id = ctx.db, ctx.user_id
    matches = await get_stage2_queue(db, user_id, run_id=run_id)
    txn_ids = {m.atomic_txn_id for m in matches}
    txn_map = (
        {
            t.id: t
            for t in (await db.execute(select(AtomicTransaction).where(AtomicTransaction.id.in_(txn_ids)))).scalars().all()
        }
        if txn_ids
        else {}
    )
    pending_matches = [
        Stage2PendingMatch(
            id=m.id,
            match_score=m.match_score,
            status=m.status.value,
            created_at=m.created_at,
            description=txn.description if (txn := txn_map.get(m.atomic_txn_id)) else None,
            amount=txn.amount if txn else None,
            txn_date=txn.txn_date if txn else None,
            confidence_tier=derive_reconciliation_score_tier(m.match_score),
        )
        for m in matches
    ]
    checks, _ = await list_checks(db, user_id, status=CheckStatus.PENDING, run_id=run_id, limit=None)
    unresolved = any(c.severity is None or c.severity != "low" for c in checks)
    return Stage2ReviewQueueResponse(
        pending_matches=pending_matches,
        consistency_checks=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        has_unresolved_checks=unresolved,
    )


@router.post("/consistency-checks/runs", response_model=ConsistencyCheckListResponse)
async def run_stage2_checks(
    request: ConsistencyCheckRunRequest, ctx: Ctx
) -> ConsistencyCheckListResponse:
    """Run consistency checks for a statement."""
    db, user_id = ctx.db, ctx.user_id
    stmt = await get_owned_or_raise(db, StatementSummary, request.statement_id, user_id, name="Statement")
    if stmt.status is BankStatementStatus.RETIRED:
        raise ResourceNotFoundError("Statement not found")
    checks = await run_all_consistency_checks(db, user_id, request.statement_id)
    await db.flush()
    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=len(checks),
    )


@router.get("/consistency-checks", response_model=ConsistencyCheckListResponse)
async def list_consistency_checks(
    ctx: ReadCtx,
    status: CheckStatus | None = None,
    check_type: CheckType | None = None,
    run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum items to return")] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConsistencyCheckListResponse:
    """List consistency checks for the current user."""
    checks, total = await list_checks(
        ctx.db, ctx.user_id, status=status, check_type=check_type, run_id=run_id, limit=limit, offset=offset
    )
    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=total,
    )


@router.post("/consistency-checks/{check_id}/resolutions", response_model=ConsistencyCheckResponse)
async def resolve_consistency_check(
    check_id: UUID, request: ResolveCheckRequest, ctx: Ctx
) -> ConsistencyCheckResponse:
    """Resolve a consistency check."""
    db, user_id = ctx.db, ctx.user_id
    check = await resolve_check(
        db, check_id, parse_check_resolution_action(request.action), user_id, request.note
    )
    await db.flush()
    return ConsistencyCheckResponse.model_validate(check)
