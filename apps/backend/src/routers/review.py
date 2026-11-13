"""Stage 2 review endpoints for bank statement reconciliation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from src.audit import InvalidCurrencyError
from src.deps import CurrentUserId, DbSession
from src.extraction import (
    AtomicTransaction,
    BankStatementStatus,
    StatementSummary,
    resolve_statement_conflicts,
    resolve_statement_transactions,
    resolve_transaction_currency,
)
from src.observability import get_logger
from src.platform import get_owned_or_404, raise_conflict, raise_not_found
from src.reconciliation import (
    CheckResolutionAction,
    CheckStatus,
    CheckType,
    ReconciliationError,
    ReconciliationMatch,
    ReconciliationStatus,
    accept_pending_matches,
    derive_reconciliation_score_tier,
    get_stage2_queue,
    has_unresolved_checks,
    list_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.schemas.review import (
    BatchApproveRequest,
    BatchApproveResponse,
    BatchRejectRequest,
    BatchRejectResponse,
    ConsistencyCheckListResponse,
    ConsistencyCheckResponse,
    ResolveCheckRequest,
    ResolveConflictsRequest,
    ResolveCurrencyRequest,
    ResolveCurrencyResponse,
    ReviewConflictCandidate,
    ReviewConflictsResolveResponse,
    ReviewConflictsResponse,
    Stage2PendingMatch,
    Stage2ReviewQueueResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/statements", tags=["review"])
conflicts_router = APIRouter(prefix="/review", tags=["review"])


async def _active_statement_or_404(db: DbSession, statement_id: UUID, user_id: UUID) -> StatementSummary:
    stmt = await get_owned_or_404(db, StatementSummary, statement_id, user_id, name="Statement")
    if stmt.status is BankStatementStatus.RETIRED:
        raise_not_found("Statement")
    return stmt


@conflicts_router.get("/conflicts/{statement_id}", response_model=ReviewConflictsResponse)
async def get_review_conflicts(
    statement_id: UUID, db: DbSession, user_id: CurrentUserId
) -> ReviewConflictsResponse:
    """Return duplicate and transfer-pair candidates for a statement."""
    statement = await _active_statement_or_404(db, statement_id, user_id)
    transactions = await resolve_statement_transactions(db, statement)

    def _candidate(txn: AtomicTransaction) -> ReviewConflictCandidate:
        return ReviewConflictCandidate(
            id=txn.id,
            txn_date=txn.txn_date,
            description=txn.description,
            amount=txn.amount,
            direction=txn.direction.value if hasattr(txn.direction, "value") else str(txn.direction),
        )

    duplicates: list[ReviewConflictCandidate] = []
    transfer_pairs: list[ReviewConflictCandidate] = []
    seen: dict[tuple, AtomicTransaction] = {}
    by_abs_amount: dict[tuple, AtomicTransaction] = {}
    for txn in transactions:
        balance_key = None if txn.balance_after is None else txn.balance_after.normalize()
        dedup_key = (txn.txn_date, txn.description.casefold(), txn.amount.copy_abs(), txn.direction, balance_key)
        if dedup_key in seen:
            duplicates.extend([_candidate(seen[dedup_key]), _candidate(txn)])
        else:
            seen[dedup_key] = txn

        transfer_key = (txn.txn_date, txn.amount.copy_abs())
        paired = by_abs_amount.get(transfer_key)
        if paired and paired.direction != txn.direction:
            transfer_pairs.extend([_candidate(paired), _candidate(txn)])
        else:
            by_abs_amount[transfer_key] = txn

    return ReviewConflictsResponse(
        duplicates=duplicates,
        transfer_pairs=transfer_pairs,
        resolved=statement.stage1_conflicts_resolved_at is not None,
    )


@conflicts_router.post("/conflicts/{statement_id}/resolve", response_model=ReviewConflictsResolveResponse)
async def resolve_review_conflicts(
    statement_id: UUID,
    request: ResolveConflictsRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReviewConflictsResolveResponse:
    """Resolve Stage-1 duplicate/transfer-pair candidates (#962)."""
    try:
        statement = await resolve_statement_conflicts(db, statement_id, user_id)
        resolved_at = statement.stage1_conflicts_resolved_at
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    logger.info(
        "stage1.conflicts.resolved",
        audit_event="stage1.conflicts.resolved",
        statement_id=str(statement_id),
        action=request.action,
        note=request.note,
    )
    return ReviewConflictsResolveResponse(resolved=True, resolved_at=resolved_at)


@conflicts_router.post("/transactions/{transaction_id}/currency", response_model=ResolveCurrencyResponse)
async def resolve_transaction_currency_endpoint(
    transaction_id: UUID,
    request: ResolveCurrencyRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ResolveCurrencyResponse:
    """Specify ISO-4217 currency for a `currency_unresolved` transaction."""
    try:
        txn = await resolve_transaction_currency(db, transaction_id, user_id=user_id, currency=request.currency)
    except InvalidCurrencyError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    response = ResolveCurrencyResponse(
        transaction_id=txn.id,
        currency=txn.currency,
        currency_unresolved=txn.currency_unresolved,
        resolved_by=txn.currency_resolved_by,
        resolved_at=txn.currency_resolved_at,
    )
    await db.commit()
    return response


@router.get("/stage2/queue", response_model=Stage2ReviewQueueResponse)
async def get_stage2_review_queue(
    db: DbSession, user_id: CurrentUserId, run_id: str | None = None
) -> Stage2ReviewQueueResponse:
    """Stage 2: Get review queue (matches + checks)."""
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
    return Stage2ReviewQueueResponse(
        pending_matches=pending_matches,
        consistency_checks=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        has_unresolved_checks=await has_unresolved_checks(db, user_id, run_id=run_id),
    )


@router.post("/{statement_id}/stage2/run-checks", response_model=ConsistencyCheckListResponse)
async def run_stage2_checks(
    statement_id: UUID, db: DbSession, user_id: CurrentUserId
) -> ConsistencyCheckListResponse:
    """Run consistency checks for a statement."""
    await _active_statement_or_404(db, statement_id, user_id)
    checks = await run_all_consistency_checks(db, user_id, statement_id)
    await db.commit()
    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=len(checks),
    )


@router.post("/consistency-checks/{check_id}/resolve", response_model=ConsistencyCheckResponse)
async def resolve_consistency_check(
    check_id: UUID, request: ResolveCheckRequest, db: DbSession, user_id: CurrentUserId
) -> ConsistencyCheckResponse:
    """Resolve a consistency check."""
    try:
        check = await resolve_check(db, check_id, CheckResolutionAction(request.action), user_id, request.note)
        await db.commit()
    except (ReconciliationError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return ConsistencyCheckResponse.model_validate(check)


@router.get("/consistency-checks/list", response_model=ConsistencyCheckListResponse)
async def list_consistency_checks(
    db: DbSession,
    user_id: CurrentUserId,
    status: CheckStatus | None = None,
    check_type: CheckType | None = None,
    run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum items to return")] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConsistencyCheckListResponse:
    """List/filter consistency checks."""
    checks, total = await list_checks(
        db, user_id, status=status, check_type=check_type, run_id=run_id, limit=limit, offset=offset
    )
    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=total,
    )


@router.post("/batch-approve-matches", response_model=BatchApproveResponse)
async def batch_approve_matches(
    request: BatchApproveRequest, db: DbSession, user_id: CurrentUserId
) -> BatchApproveResponse:
    """Batch approve matches (blocked by unresolved consistency checks)."""
    if await has_unresolved_checks(db, user_id, run_id=request.run_id):
        raise_conflict("Cannot batch approve while there are unresolved consistency checks")
    if not request.match_ids:
        return BatchApproveResponse(approved_count=0, journal_entries_reconciled=0)

    query = (
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(
            ReconciliationMatch.id.in_(request.match_ids),
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            AtomicTransaction.user_id == user_id,
        )
        .order_by(ReconciliationMatch.id)
        .with_for_update(of=ReconciliationMatch)
    )
    if request.run_id:
        query = query.where(ReconciliationMatch.run_id == request.run_id)
    matches = list((await db.execute(query)).scalars().all())
    try:
        reconciled = await accept_pending_matches(db, matches, user_id=user_id)
    except ReconciliationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return BatchApproveResponse(approved_count=len(matches), journal_entries_reconciled=reconciled)


@router.post("/batch-reject-matches", response_model=BatchRejectResponse)
async def batch_reject_matches(
    request: BatchRejectRequest, db: DbSession, user_id: CurrentUserId
) -> BatchRejectResponse:
    """Batch reject matches."""
    if not request.match_ids:
        return BatchRejectResponse(rejected_count=0)
    matches = list(
        (
            await db.execute(
                select(ReconciliationMatch)
                .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
                .where(
                    ReconciliationMatch.id.in_(request.match_ids),
                    ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
                    AtomicTransaction.user_id == user_id,
                )
            )
        ).scalars().all()
    )
    for match in matches:
        match.status = ReconciliationStatus.REJECTED
        match.version += 1
    await db.commit()
    return BatchRejectResponse(rejected_count=len(matches))
