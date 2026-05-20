"""Stage 2 review endpoints for bank statement reconciliation."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from src.deps import CurrentUserId, DbSession
from src.models import (
    BankStatement,
    BankStatementTransaction,
    JournalEntry,
    JournalEntryStatus,
)
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
from src.services.confidence_tier import derive_confidence_tier
from src.services.consistency_checks import (
    get_pending_checks,
    has_unresolved_checks,
    list_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.services.review_queue import accept_match as accept_match_service, get_stage2_queue
from src.services.source_type_priority import STATEMENT_SOURCE_TYPES
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
        transaction = match.transaction
        pending_matches.append(
            {
                "id": str(match.id),
                "match_score": match.match_score,
                "status": match.status.value,
                "created_at": match.created_at.isoformat() if match.created_at else None,
                "description": transaction.description if transaction else None,
                "amount": transaction.amount if transaction else None,
                "txn_date": transaction.txn_date.isoformat() if transaction else None,
                "confidence_tier": derive_confidence_tier("bank_statement"),
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
            "journal_entries_created": 0,
            "journal_entries_reconciled": 0,
        }

    if not request.match_ids:
        return {
            "success": True,
            "approved_count": 0,
            "journal_entries_created": 0,
            "journal_entries_reconciled": 0,
        }

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
    journal_entries_created = 0
    journal_entries_reconciled = 0
    for match in matches:
        before_entry_ids = set(match.journal_entry_ids or [])
        had_source_entry = False
        if match.bank_txn_id and not before_entry_ids:
            existing_entry_result = await db.execute(
                select(JournalEntry.id)
                .where(JournalEntry.user_id == user_id)
                .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
                .where(JournalEntry.source_id == match.bank_txn_id)
                .where(JournalEntry.status != JournalEntryStatus.VOID)
                .limit(1)
            )
            had_source_entry = existing_entry_result.scalar_one_or_none() is not None

        try:
            accepted_match = await accept_match_service(db, str(match.id), user_id=user_id)
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        after_entry_ids = set(accepted_match.journal_entry_ids or [])
        approved_count += 1
        if not before_entry_ids and not had_source_entry:
            journal_entries_created += len(after_entry_ids)
        if after_entry_ids:
            reconciled_entries_result = await db.execute(
                select(JournalEntry.id)
                .where(JournalEntry.id.in_([UUID(entry_id) for entry_id in after_entry_ids]))
                .where(JournalEntry.user_id == user_id)
                .where(JournalEntry.status == JournalEntryStatus.RECONCILED)
            )
            journal_entries_reconciled += len(reconciled_entries_result.scalars().all())

    await db.commit()

    return {
        "success": True,
        "approved_count": approved_count,
        "journal_entries_created": journal_entries_created,
        "journal_entries_reconciled": journal_entries_reconciled,
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
