"""Stage 2 review endpoints for bank statement reconciliation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import CurrentUserId, DbSession, ReadDbSession
from src.extraction import (
    AtomicTransaction,
    BankStatementStatus,
    StatementSummary,
    resolve_statement_conflicts,
    resolve_statement_transactions,
)
from src.observability import get_logger
from src.platform import ResourceNotFoundError, get_owned_or_raise
from src.reconciliation import (
    CheckStatus,
    CheckType,
    derive_reconciliation_score_tier,
    get_stage2_queue,
    list_checks,
    parse_check_resolution_action,
    resolve_check,
    run_all_consistency_checks,
)
from src.schemas.review import (
    ConsistencyCheckListResponse,
    ConsistencyCheckResponse,
    ResolveCheckRequest,
    ResolveConflictsRequest,
    ReviewConflictCandidate,
    ReviewConflictsResolveResponse,
    ReviewConflictsResponse,
    Stage2PendingMatch,
    Stage2ReviewQueueResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/statements", tags=["review"])


async def _active_statement_or_404(db: AsyncSession, statement_id: UUID, user_id: UUID) -> StatementSummary:
    stmt = await get_owned_or_raise(db, StatementSummary, statement_id, user_id, name="Statement")
    if stmt.status is BankStatementStatus.RETIRED:
        raise ResourceNotFoundError("Statement not found")
    return stmt


@router.get("/{statement_id}/conflicts", response_model=ReviewConflictsResponse)
async def get_review_conflicts(
    statement_id: UUID, db: ReadDbSession, user_id: CurrentUserId
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


@router.post("/{statement_id}/conflicts/resolve", response_model=ReviewConflictsResolveResponse)
async def resolve_review_conflicts(
    statement_id: UUID,
    request: ResolveConflictsRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReviewConflictsResolveResponse:
    """Resolve Stage-1 duplicate/transfer-pair candidates (#962)."""
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


@router.get("/stage2/queue", response_model=Stage2ReviewQueueResponse)
async def get_stage2_review_queue(
    db: ReadDbSession, user_id: CurrentUserId, run_id: str | None = None
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
    unresolved = any(c.severity is None or c.severity != "low" for c in checks)
    return Stage2ReviewQueueResponse(
        pending_matches=pending_matches,
        consistency_checks=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        has_unresolved_checks=unresolved,
    )


@router.post("/{statement_id}/stage2/run-checks", response_model=ConsistencyCheckListResponse)
async def run_stage2_checks(
    statement_id: UUID, db: DbSession, user_id: CurrentUserId
) -> ConsistencyCheckListResponse:
    """Run consistency checks for a statement."""
    await _active_statement_or_404(db, statement_id, user_id)
    checks = await run_all_consistency_checks(db, user_id, statement_id)
    await db.flush()
    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=len(checks),
    )


@router.post("/consistency-checks/{check_id}/resolve", response_model=ConsistencyCheckResponse)
async def resolve_consistency_check(
    check_id: UUID, request: ResolveCheckRequest, db: DbSession, user_id: CurrentUserId
) -> ConsistencyCheckResponse:
    """Resolve a consistency check."""
    check = await resolve_check(
        db, check_id, parse_check_resolution_action(request.action), user_id, request.note
    )
    await db.flush()
    return ConsistencyCheckResponse.model_validate(check)


@router.get("/consistency-checks", response_model=ConsistencyCheckListResponse)
async def list_consistency_checks(
    db: ReadDbSession,
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
