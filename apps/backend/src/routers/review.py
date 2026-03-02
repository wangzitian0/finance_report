"""Stage 2 review endpoints for bank statement reconciliation."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from src.deps import CurrentUserId, DbSession
from src.models import BankStatement, BankStatementTransaction
from src.models.consistency_check import CheckStatus, CheckType
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.schemas.review import (
    BatchApproveRequest,
    BatchRejectRequest,
    ConsistencyCheckListResponse,
    ConsistencyCheckResponse,
    ResolveCheckRequest,
    Stage2ReviewQueueResponse,
)
from src.services.consistency_checks import (
    get_pending_checks,
    has_unresolved_checks,
    list_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.services.review_queue import get_stage2_queue
from src.utils import raise_not_found

router = APIRouter(prefix="/statements", tags=["review"])


@router.get("/stage2/queue", response_model=Stage2ReviewQueueResponse)
async def get_stage2_review_queue(
    db: DbSession,
    user_id: CurrentUserId,
) -> Stage2ReviewQueueResponse:
    """Stage 2: Get review queue (matches + checks)."""
    matches = await get_stage2_queue(db, user_id)
    pending_matches = []
    for match in matches:
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
    checks, total = await list_checks(db, user_id, status=status, check_type=check_type, limit=limit, offset=offset)

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
