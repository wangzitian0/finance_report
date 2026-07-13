"""Stage 2 review endpoints for bank statement reconciliation."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from src.audit import STATEMENT_SOURCE_TYPES
from src.audit.money import InvalidCurrencyError
from src.deps import CurrentUserId, DbSession
from src.extraction import (
    resolve_statement_conflicts,
    resolve_statement_transactions,
    resolve_transaction_currency,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, JournalEntryStatus
from src.models.statement_summary import StatementSummary
from src.observability import get_logger
from src.platform import get_owned_or_404, raise_conflict
from src.reconciliation import (
    ReconciliationMatch,
    ReconciliationStatus,
    accept_match as accept_match_service,
    get_pending_checks,
    get_stage2_queue,
    has_unresolved_checks,
    list_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.reconciliation.orm.consistency_check import CheckStatus, CheckType
from src.reporting import derive_reconciliation_score_tier
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


@conflicts_router.get("/conflicts/{statement_id}", response_model=ReviewConflictsResponse)
async def get_review_conflicts(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReviewConflictsResponse:
    """Return duplicate and transfer-pair candidates for a statement."""
    statement = await get_owned_or_404(db, StatementSummary, statement_id, user_id, name="Statement")

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
    for txn in transactions:
        # Keep duplicate detection consistent with the approval guard / dedup disambiguator:
        # a different running balance means the dedup layer kept these as distinct transactions.
        balance_key = None if txn.balance_after is None else txn.balance_after.normalize()
        key = (txn.txn_date, txn.description.casefold(), txn.amount.copy_abs(), txn.direction, balance_key)
        if key in seen:
            duplicates.extend([_candidate(seen[key]), _candidate(txn)])
        else:
            seen[key] = txn

    by_abs_amount: dict[tuple, AtomicTransaction] = {}
    for txn in transactions:
        key = (txn.txn_date, txn.amount.copy_abs())
        paired = by_abs_amount.get(key)
        if paired and paired.direction != txn.direction:
            transfer_pairs.extend([_candidate(paired), _candidate(txn)])
        else:
            by_abs_amount[key] = txn

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
    """Resolve a statement's Stage-1 duplicate/transfer-pair candidates (#962).

    Records the reviewer's decision so the approval guard stops blocking, instead
    of leaving a legitimately-conflicting statement permanently stuck in ``parsed``.
    """
    try:
        statement = await resolve_statement_conflicts(db, statement_id, user_id)
        # Read before commit: commit expires the ORM object, and a post-commit
        # attribute access would trigger a lazy load outside the async greenlet.
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


@conflicts_router.post(
    "/transactions/{transaction_id}/currency",
    response_model=ResolveCurrencyResponse,
)
async def resolve_transaction_currency_endpoint(
    transaction_id: UUID,
    request: ResolveCurrencyRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ResolveCurrencyResponse:
    """Reviewer specifies the currency for a ``currency_unresolved`` transaction (AC12.40.3).

    Validates the chosen code as ISO-4217 (``src.audit.money.Currency``), clears the
    unresolved flag, and records the resolution audit (who/when). Only after this
    can the transaction be promoted to a journal entry (AC12.40.4).
    """
    try:
        txn = await resolve_transaction_currency(
            db,
            transaction_id,
            user_id=user_id,
            currency=request.currency,
        )
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
    db: DbSession,
    user_id: CurrentUserId,
    run_id: str | None = None,
) -> Stage2ReviewQueueResponse:
    """Stage 2: Get review queue (matches + checks)."""
    matches = await get_stage2_queue(db, user_id, run_id=run_id)
    txn_ids = {match.atomic_txn_id for match in matches}
    txn_map: dict[UUID, AtomicTransaction] = {}
    if txn_ids:
        txn_result = await db.execute(select(AtomicTransaction).where(AtomicTransaction.id.in_(txn_ids)))
        txn_map = {txn.id: txn for txn in txn_result.scalars().all()}
    pending_matches = []
    for match in matches:
        transaction = txn_map.get(match.atomic_txn_id)
        pending_matches.append(
            Stage2PendingMatch(
                id=match.id,
                match_score=match.match_score,
                status=match.status.value,
                created_at=match.created_at,
                description=transaction.description if transaction else None,
                amount=transaction.amount if transaction else None,
                txn_date=transaction.txn_date if transaction else None,
                confidence_tier=derive_reconciliation_score_tier(match.match_score),
            )
        )

    checks = await get_pending_checks(db, user_id, run_id=run_id, limit=None)

    return Stage2ReviewQueueResponse(
        pending_matches=pending_matches,
        consistency_checks=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        has_unresolved_checks=await has_unresolved_checks(db, user_id, run_id=run_id),
    )


@router.post("/{statement_id}/stage2/run-checks", response_model=ConsistencyCheckListResponse)
async def run_stage2_checks(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ConsistencyCheckListResponse:
    """Run consistency checks for a statement."""
    # Existence/ownership guard (404); the checks below key off statement_id.
    await get_owned_or_404(db, StatementSummary, statement_id, user_id, name="Statement")

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return ConsistencyCheckResponse.model_validate(check)


@router.get("/consistency-checks/list", response_model=ConsistencyCheckListResponse)
async def list_consistency_checks(
    db: DbSession,
    user_id: CurrentUserId,
    status: CheckStatus | None = None,
    check_type: CheckType | None = None,
    run_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ConsistencyCheckListResponse:
    """List/filter consistency checks."""
    checks, total = await list_checks(
        db,
        user_id,
        status=status,
        check_type=check_type,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )

    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=total,
    )


@router.post("/batch-approve-matches", response_model=BatchApproveResponse)
async def batch_approve_matches(
    request: BatchApproveRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BatchApproveResponse:
    """Batch approve matches (blocked by unresolved checks).

    #1001: unresolved consistency checks now raise a 409 (structured
    ``ErrorResponse``) instead of returning ``{"success": false}`` in a 200 body.
    """
    if await has_unresolved_checks(db, user_id, run_id=request.run_id):
        raise_conflict("Cannot batch approve while there are unresolved consistency checks")

    if not request.match_ids:
        return BatchApproveResponse(
            approved_count=0,
            journal_entries_created=0,
            journal_entries_reconciled=0,
        )

    matches_query = (
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(
            ReconciliationMatch.id.in_(request.match_ids),
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            AtomicTransaction.user_id == user_id,
        )
    )
    if request.run_id:
        matches_query = matches_query.where(ReconciliationMatch.run_id == request.run_id)
    result = await db.execute(matches_query)
    matches = list(result.scalars().all())

    approved_count = 0
    journal_entries_created = 0
    journal_entries_reconciled = 0
    for match in matches:
        before_entry_ids = set(match.journal_entry_ids or [])
        had_source_entry = False
        if match.atomic_txn_id and not before_entry_ids:
            existing_entry_result = await db.execute(
                select(JournalEntry.id)
                .where(JournalEntry.user_id == user_id)
                .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
                .where(JournalEntry.source_id == match.atomic_txn_id)
                .where(JournalEntry.status != JournalEntryStatus.VOID)
                .limit(1)
            )
            had_source_entry = existing_entry_result.scalar_one_or_none() is not None

        try:
            accepted_match = await accept_match_service(db, str(match.id), user_id=user_id)
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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

    return BatchApproveResponse(
        approved_count=approved_count,
        journal_entries_created=journal_entries_created,
        journal_entries_reconciled=journal_entries_reconciled,
    )


@router.post("/batch-reject-matches", response_model=BatchRejectResponse)
async def batch_reject_matches(
    request: BatchRejectRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BatchRejectResponse:
    """Batch reject matches."""
    if not request.match_ids:
        return BatchRejectResponse(rejected_count=0)

    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(
            ReconciliationMatch.id.in_(request.match_ids),
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            AtomicTransaction.user_id == user_id,
        )
    )
    matches = list(result.scalars().all())

    rejected_count = 0
    for match in matches:
        match.status = ReconciliationStatus.REJECTED
        match.version += 1
        rejected_count += 1

    await db.commit()

    return BatchRejectResponse(rejected_count=rejected_count)
