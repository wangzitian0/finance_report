"""Review API router tests.

Tests endpoints in src/routers/review.py covering:
- Stage 2 review queue and run filtering
- Consistency check listing and resolution
- Match batch approval and rejection
- Conflict candidate resolution
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select

from src.audit import (
    STATEMENT_SOURCE_TYPES,
    JournalEntrySourceType,
)
from src.extraction import (
    BankStatementStatus,
    EconomicIntent,
    Stage1Status,
)
from src.extraction.extension import statement_validation as statement_validation_mod
from src.extraction.extension.review_queue import create_entry_from_txn
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.reconciliation.extension.review_queue import accept_match as accept_match_service
from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.routers import review as review_router, statements as statements_router
from src.schemas.review import (
    BatchApproveRequest,
    BatchRejectRequest,
    ResolveCheckRequest,
    ResolveConflictsRequest,
    Stage1ApprovalRequest,
)
from tests.api._statement_router_fixtures import (
    add_reviewed_disposition_rule,
    add_txn,
    build_statement,
    create_statement_account,
)
from tests.statement_ingestion import anchored_reviewed_posting_inputs


async def _seed_approved_statement_with_txn(
    db,
    user_id,
    name: str = "DBS",
    amount: Decimal = Decimal("50.00"),
    description: str = "Payment",
    txn_date: date = date(2025, 1, 15),
    direction: str = "OUT",
):
    account = await create_statement_account(db, user_id, f"{name} Account")
    statement = build_statement(user_id, f"hash_{uuid4().hex[:8]}", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(db, statement, txn_date=txn_date, description=description, amount=amount, direction=direction)
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return account, statement, txn


async def _seed_approved_statement_with_posted_txn(
    db,
    user_id,
    name: str = "DBS",
    amount: Decimal = Decimal("50.00"),
    description: str = "Payment",
    txn_date: date = date(2025, 1, 15),
    direction: str = "OUT",
    intent: EconomicIntent = EconomicIntent.EXPENSE,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
):
    account, statement, txn = await _seed_approved_statement_with_txn(
        db,
        user_id,
        name=name,
        amount=amount,
        description=description,
        txn_date=txn_date,
        direction=direction,
    )
    decision, counter_account, source_decision, trace_emitter = await anchored_reviewed_posting_inputs(
        db,
        user_id=user_id,
        transaction=txn,
        intent=intent,
    )
    entry = await create_entry_from_txn(
        db,
        txn,
        user_id=user_id,
        auto_post=True,
        source_type=source_type,
        disposition=decision,
        counter_account=counter_account,
        source_decision=source_decision,
        trace_emitter=trace_emitter,
    )
    await db.flush()
    return account, statement, txn, entry


async def test_get_stage2_review_queue_empty(db, test_user):
    """Given no pending matches or checks,
    When get_stage2_review_queue is called,
    Then it returns empty queue (lines 844-867).
    """
    result = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id)

    assert result.pending_matches == []
    assert result.consistency_checks == []
    assert result.has_unresolved_checks is False


async def test_get_stage2_review_queue_with_pending_match(db, test_user):
    """AC-reconciliation.bank-side-amount.4: AC4.9.4: Given a statement with a pending-review reconciliation match,
    When get_stage2_review_queue is called,
    Then it returns the match in pending_matches with tier derived from match_score.
    """
    from src.reconciliation import ReconciliationMatch, ReconciliationStatus

    _, _, txn = await _seed_approved_statement_with_txn(db, test_user.id, "Stage 2 Queue")

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        match_score=75,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    result = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id)

    assert len(result.pending_matches) == 1
    assert result.pending_matches[0].status == "pending_review"
    assert result.pending_matches[0].match_score == 75
    assert result.pending_matches[0].confidence_tier == "MEDIUM"


async def test_run_stage2_checks_success(db, test_user):
    """Given an existing statement,
    When run_stage2_checks is called,
    Then it runs consistency checks and returns results (lines 881-891).
    """
    account = await create_statement_account(db, test_user.id, "Stage 2 Checks Account")
    statement = build_statement(test_user.id, "hash_s2_checks", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    result = await review_router.run_stage2_checks(statement_id=statement_id, db=db, user_id=test_user.id)

    assert result.total >= 0
    assert isinstance(result.items, list)


async def test_run_stage2_checks_not_found(db, test_user):
    """Given a non-existent statement,
    When run_stage2_checks is called,
    Then it raises 404.
    """
    with pytest.raises(HTTPException) as exc:
        await review_router.run_stage2_checks(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_resolve_consistency_check_success(db, test_user):
    """Given a pending consistency check,
    When resolve_consistency_check is called with action='approve',
    Then it resolves the check (lines 905-911).
    """
    from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1", "txn2"],
        details={"count": 2, "amount": "100.00"},
        severity="high",
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)
    check_id = check.id

    result = await review_router.resolve_consistency_check(
        check_id=check_id,
        request=ResolveCheckRequest(action="approve", note="Looks fine"),
        db=db,
        user_id=test_user.id,
    )

    assert result.status == CheckStatus.APPROVED
    assert result.resolution_note == "Looks fine"


async def test_resolve_consistency_check_invalid_action(db, test_user):
    """Given a pending consistency check,
    When resolve_consistency_check is called with an invalid action,
    Then it raises 400.
    """
    from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1"],
        details={"count": 1},
        severity="high",
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)
    check_id = check.id

    with pytest.raises(HTTPException) as exc:
        await review_router.resolve_consistency_check(
            check_id=check_id,
            request=ResolveCheckRequest(action="invalid"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400


async def test_resolve_consistency_check_not_found(db, test_user):
    """Given a non-existent check ID,
    When resolve_consistency_check is called,
    Then it raises 400.
    """
    with pytest.raises(HTTPException) as exc:
        await review_router.resolve_consistency_check(
            check_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=ResolveCheckRequest(action="approve"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400


async def test_list_consistency_checks_empty(db, test_user):
    """Given no consistency checks,
    When list_consistency_checks is called,
    Then it returns an empty list (lines 924-947).
    """
    result = await review_router.list_consistency_checks(db=db, user_id=test_user.id)

    assert result.total == 0
    assert result.items == []


async def test_list_consistency_checks_with_filters(db, test_user):
    """Given multiple consistency checks,
    When list_consistency_checks is called with status and type filters,
    Then it returns filtered results (lines 934-939).
    """
    from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check1 = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1"],
        details={"count": 1},
        severity="high",
    )
    check2 = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.TRANSFER_PAIR,
        status=CheckStatus.APPROVED,
        related_txn_ids=["txn2"],
        details={"amount": "50.00"},
        severity="medium",
    )
    db.add(check1)
    db.add(check2)
    await db.commit()

    # Filter by status
    result = await review_router.list_consistency_checks(db=db, user_id=test_user.id, status=CheckStatus.PENDING)
    assert result.total == 1
    assert result.items[0].check_type == CheckType.DUPLICATE

    # Filter by check_type
    result2 = await review_router.list_consistency_checks(
        db=db, user_id=test_user.id, check_type=CheckType.TRANSFER_PAIR
    )
    assert result2.total == 1
    assert result2.items[0].status == CheckStatus.APPROVED


async def test_batch_approve_matches_blocked_by_unresolved_checks(db, test_user):
    """AC-reconciliation.stage2-batch.1: AC16.22.3: Given unresolved consistency checks,
    When batch_approve_matches is called,
    Then it returns error (lines 960-965).
    """
    from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1"],
        details={"count": 1},
        severity="high",
    )
    db.add(check)
    await db.commit()

    # #1001: unresolved checks now raise a 409 structured error instead of
    # returning {"success": false} in a 200 body.
    with pytest.raises(HTTPException) as exc:
        await review_router.batch_approve_matches(
            request=BatchApproveRequest(match_ids=[]),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "unresolved" in exc.value.detail


async def test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts(db, test_user):
    """AC-reconciliation.conflict-resolution.1: AC16.32.1: Stage 1 approval cannot bypass unresolved duplicate candidates."""
    account = await create_statement_account(db, test_user.id, "DBS Stage 1 Conflict")
    statement = build_statement(test_user.id, "hash_stage1_conflict", 90)
    statement.status = BankStatementStatus.PARSED
    statement.stage1_status = Stage1Status.PENDING_REVIEW
    statement.account_id = account.id
    statement.opening_balance = Decimal("100.00")
    statement.closing_balance = Decimal("140.00")
    db.add(statement)
    await db.commit()

    for _ in range(2):
        await add_txn(
            db,
            statement,
            txn_date=date(2025, 1, 15),
            description="Duplicate deposit",
            amount=Decimal("20.00"),
            direction="IN",
        )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            request=Stage1ApprovalRequest(notes=None),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "unresolved duplicate or transfer-pair" in exc_info.value.detail


async def test_AC16_32_1_stage1_approval_blocks_unresolved_transfer_pairs(db, test_user):
    """AC16.32.1: Stage 1 approval cannot bypass unresolved transfer-pair candidates."""
    account = await create_statement_account(db, test_user.id, "Transfer Conflict Account")
    statement = build_statement(test_user.id, "hash_stage1_transfer_conflict", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Transfer out",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Transfer in",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            request=Stage1ApprovalRequest(notes=None),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "unresolved duplicate or transfer-pair" in exc_info.value.detail


async def test_AC16_34_1_resolve_unblocks_stage1_approval(db, test_user):
    """AC-reconciliation.conflict-resolution.2: AC16.34.1: resolving the conflict candidates unblocks Stage 1 approval.

    A statement with an inherent duplicate is no longer permanently stuck in
    ``parsed`` once the reviewer confirms the rows are genuinely distinct.
    """
    user_id = test_user.id  # capture before any rollback expires the fixture object
    account = await create_statement_account(db, test_user.id, "Resolve Conflict Account")
    statement = build_statement(test_user.id, "hash_stage1_resolve", 90)
    statement.status = BankStatementStatus.PARSED
    statement.stage1_status = Stage1Status.PENDING_REVIEW
    statement.account_id = account.id
    statement.opening_balance = Decimal("100.00")
    statement.closing_balance = Decimal("140.00")
    db.add(statement)
    await db.commit()
    statement_id = statement.id  # capture before commits/rollbacks expire the object

    for _ in range(2):
        await add_txn(
            db,
            statement,
            txn_date=date(2025, 1, 15),
            description="Duplicate deposit",
            amount=Decimal("20.00"),
            direction="IN",
        )
    await add_reviewed_disposition_rule(
        db,
        user_id=user_id,
        keyword="duplicate deposit",
        account_type=AccountType.INCOME,
        category="SALARY",
    )
    await db.commit()

    # Before resolving, approval is blocked.
    with pytest.raises(HTTPException) as exc_info:
        await statements_router.approve_statement_stage1(
            statement_id=statement_id,
            request=Stage1ApprovalRequest(),
            db=db,
            user_id=user_id,
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    # Resolve the candidates via the Stage-1 conflict-resolution endpoint.
    resolve_response = await review_router.resolve_review_conflicts(
        statement_id=statement_id,
        request=ResolveConflictsRequest(action="confirm_distinct"),
        db=db,
        user_id=user_id,
    )
    assert resolve_response.resolved is True
    assert resolve_response.resolved_at is not None

    # The conflicts endpoint exposes the persisted marker so the UI can derive the
    # blocked state from the server rather than ephemeral client state.
    conflicts_after = await review_router.get_review_conflicts(statement_id=statement_id, db=db, user_id=user_id)
    assert conflicts_after.resolved is True

    # Approval now succeeds despite the duplicate candidate (no HTTP 400 raised).
    approved = await statements_router.approve_statement_stage1(
        statement_id=statement_id,
        request=Stage1ApprovalRequest(),
        db=db,
        user_id=user_id,
    )
    assert approved.id == statement_id
    assert approved.status == BankStatementStatus.APPROVED


async def test_AC16_34_1_resolve_conflicts_404_for_unknown_statement(db, test_user):
    """AC16.34.1: resolving conflicts for a missing statement returns 404."""
    with pytest.raises(HTTPException) as exc_info:
        await review_router.resolve_review_conflicts(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=ResolveConflictsRequest(action="confirm_distinct"),
            db=db,
            user_id=test_user.id,
        )
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


async def test_AC16_34_2_reject_clears_conflict_resolution(db, test_user):
    """AC-reconciliation.conflict-resolution.3: AC16.34.2: a reject/reparse clears a prior conflict resolution so the
    fresh transaction set must be re-reviewed."""
    statement = build_statement(test_user.id, "hash_stage1_resolve_reset", 90)
    statement.status = BankStatementStatus.PARSED
    db.add(statement)
    await db.commit()
    statement_id = statement.id  # capture before commit expires the object

    await review_router.resolve_review_conflicts(
        statement_id=statement_id,
        request=ResolveConflictsRequest(action="confirm_distinct"),
        db=db,
        user_id=test_user.id,
    )
    await db.refresh(statement)
    assert statement.stage1_conflicts_resolved_at is not None

    await statement_validation_mod.reject_statement(db, statement_id, test_user.id, reason="reparse")
    await db.commit()
    await db.refresh(statement)
    assert statement.stage1_conflicts_resolved_at is None


async def test_AC16_32_3_stage2_queue_returns_all_pending_checks(db, test_user):
    """AC-reconciliation.review-hardening.1: AC16.32.3: Stage 2 queue includes the full unresolved blocker set."""
    db.add_all(
        [
            ConsistencyCheck(
                user_id=test_user.id,
                check_type=CheckType.DUPLICATE,
                status=CheckStatus.PENDING,
                related_txn_ids=[f"txn-{idx}"],
                details={"message": f"Duplicate candidate {idx}"},
                severity="high",
            )
            for idx in range(55)
        ]
    )
    await db.commit()

    result = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id)

    assert len(result.consistency_checks) == 55


async def test_AC19_11_1_consistency_check_list_filters_by_run_id(db, test_user):
    """AC19.11.1: Consistency check list supports run-scoped review pages."""
    db.add_all(
        [
            ConsistencyCheck(
                user_id=test_user.id,
                run_id="run-123",
                check_type=CheckType.DUPLICATE,
                status=CheckStatus.PENDING,
                related_txn_ids=["txn-in-run"],
                details={"message": "Run scoped duplicate"},
                severity="high",
            ),
            ConsistencyCheck(
                user_id=test_user.id,
                run_id="run-456",
                check_type=CheckType.DUPLICATE,
                status=CheckStatus.PENDING,
                related_txn_ids=["txn-other-run"],
                details={"message": "Other run duplicate"},
                severity="high",
            ),
        ]
    )
    await db.commit()

    result = await review_router.list_consistency_checks(db=db, user_id=test_user.id, run_id="run-123")

    assert result.total == 1
    assert result.items[0].related_txn_ids == ["txn-in-run"]


async def test_AC19_11_1_stage2_run_queue_filters_by_run_id(db, test_user):
    """AC-reconciliation.run-scoped-review.1: AC19.11.1: Run review queues and approval are scoped to the requested run."""
    account = await create_statement_account(db, test_user.id, "DBS Run Scope")
    statement = build_statement(test_user.id, "hash_stage2_run_scope", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn_in_run = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 16),
        description="Run scoped payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    txn_other_run = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 17),
        description="Other run payment",
        amount=Decimal("60.00"),
        direction="OUT",
    )
    db.add_all([txn_in_run, txn_other_run])
    await db.commit()
    await db.refresh(txn_in_run)
    await db.refresh(txn_other_run)

    # Reconciliation confirms an existing, economically reviewed entry. It no
    # longer manufactures one from a pending match without semantic context.
    decision, counter_account, source_decision, trace_emitter = await anchored_reviewed_posting_inputs(
        db,
        user_id=test_user.id,
        transaction=txn_in_run,
        intent=EconomicIntent.EXPENSE,
    )
    await create_entry_from_txn(
        db,
        txn_in_run,
        user_id=test_user.id,
        auto_post=True,
        disposition=decision,
        counter_account=counter_account,
        source_decision=source_decision,
        trace_emitter=trace_emitter,
    )

    in_run_match = ReconciliationMatch(
        atomic_txn_id=txn_in_run.id,
        run_id="run-123",
        match_score=95,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    other_run_match = ReconciliationMatch(
        atomic_txn_id=txn_other_run.id,
        run_id="run-456",
        match_score=95,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add_all([in_run_match, other_run_match])
    await db.commit()

    queue = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id, run_id="run-123")

    assert [str(match.id) for match in queue.pending_matches] == [str(in_run_match.id)]

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[in_run_match.id, other_run_match.id], run_id="run-123"),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1
    await db.refresh(in_run_match)
    await db.refresh(other_run_match)
    assert in_run_match.status == ReconciliationStatus.ACCEPTED
    assert other_run_match.status == ReconciliationStatus.PENDING_REVIEW


async def test_batch_approve_matches_empty_list(db, test_user):
    """Given no unresolved checks and empty match_ids,
    When batch_approve_matches is called,
    Then it returns success with 0 approved (line 968).
    """
    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 0


async def test_batch_approve_matches_success(db, test_user):
    """Given pending-review matches and no unresolved checks,
    When batch_approve_matches is called with match IDs,
    Then it approves all matching records (lines 970-993).
    """
    from src.reconciliation import ReconciliationMatch, ReconciliationStatus

    _, _, txn, _ = await _seed_approved_statement_with_posted_txn(db, test_user.id, "DBS Batch Approval")
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        match_score=75,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match.id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1


async def test_batch_approve_matches_reconciles_referenced_entry(db, test_user):
    """AC-reconciliation.stage2-batch.5: AC16.24.4: Batch approving a pending Stage 2 match reconciles referenced ledger entries."""
    _, _, txn, entry = await _seed_approved_statement_with_posted_txn(
        db,
        test_user.id,
        "DBS Batch Referenced",
        txn_date=date(2025, 1, 16),
        description="Referenced entry payment",
    )
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match.id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1
    assert result.journal_entries_created == 0
    assert result.journal_entries_reconciled == 1

    await db.refresh(match)
    await db.refresh(txn)
    await db.refresh(entry)
    assert match.status == ReconciliationStatus.ACCEPTED
    assert entry.status == JournalEntryStatus.RECONCILED


async def test_batch_approve_matches_without_entry_requires_review(db, test_user):
    """AC-reconciliation.stage2-batch.2: Stage 2 cannot invent economic meaning."""
    user_id = test_user.id
    _, _, txn = await _seed_approved_statement_with_txn(
        db,
        user_id,
        "DBS Batch Missing",
        txn_date=date(2025, 1, 17),
        description="Missing entry payment",
    )
    txn_id = txn.id

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await review_router.batch_approve_matches(
            request=BatchApproveRequest(match_ids=[match.id]),
            db=db,
            user_id=user_id,
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Authoritative economic disposition" in str(exc_info.value.detail)

    await db.refresh(match)
    assert match.status == ReconciliationStatus.PENDING_REVIEW
    assert match.journal_entry_ids == []

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn_id)
    )
    assert list(entry_result.scalars().all()) == []


async def test_accept_match_retry_is_idempotent_after_success(db, test_user):
    """AC-reconciliation.bank-side-amount.2: AC4.9.2: Retrying an accepted match must not mutate version or duplicate posting side effects."""
    _, _, txn, _ = await _seed_approved_statement_with_posted_txn(
        db,
        test_user.id,
        "DBS Accept Retry",
        txn_date=date(2025, 1, 18),
        description="Retry-safe payment",
    )
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    first = await accept_match_service(db, str(match.id), user_id=test_user.id)
    await db.commit()
    first_version = first.version
    first_entry_ids = list(first.journal_entry_ids or [])

    second = await accept_match_service(db, str(match.id), user_id=test_user.id)
    await db.commit()

    assert second.status == ReconciliationStatus.ACCEPTED
    assert second.version == first_version
    assert second.journal_entry_ids == first_entry_ids

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert len(list(entry_result.scalars().all())) == 1


async def test_batch_approve_matches_reuses_existing_source_entry(db, test_user):
    """AC16.24.4: Batch approval links an existing source journal entry instead of duplicating it."""
    _, _, txn, entry = await _seed_approved_statement_with_posted_txn(
        db,
        test_user.id,
        "DBS Batch Existing Source",
        txn_date=date(2025, 1, 18),
        description="Existing source entry payment",
    )
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match.id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1
    assert result.journal_entries_created == 0
    assert result.journal_entries_reconciled == 1

    await db.refresh(match)
    await db.refresh(entry)
    assert match.journal_entry_ids == [str(entry.id)]
    assert entry.status == JournalEntryStatus.RECONCILED

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert len(list(entry_result.scalars().all())) == 1


async def test_create_entry_from_txn_auto_post_rejects_inactive_statement_account(db, test_user):
    """AC-reconciliation.bank-side-amount.3: AC4.9.3: Auto-posted statement entries must satisfy regular posting account invariants."""
    account = await create_statement_account(db, test_user.id, "DBS Inactive Statement Account")
    account.is_active = False
    statement = build_statement(test_user.id, "hash_batch_inactive_account", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Inactive mapped account payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    decision, counter_account, source_decision, trace_emitter = await anchored_reviewed_posting_inputs(
        db,
        user_id=test_user.id,
        transaction=txn,
        intent=EconomicIntent.EXPENSE,
    )

    with pytest.raises(ValueError, match="active asset"):
        await create_entry_from_txn(
            db,
            txn,
            user_id=test_user.id,
            auto_post=True,
            disposition=decision,
            counter_account=counter_account,
            source_decision=source_decision,
            trace_emitter=trace_emitter,
        )

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert list(entry_result.scalars().all()) == []
    assert (
        await db.scalar(
            select(Account.id)
            .where(Account.user_id == test_user.id)
            .where(Account.name.in_(("Income - Uncategorized", "Expense - Uncategorized")))
            .limit(1)
        )
    ) is None


async def test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph(
    db,
    test_user,
):
    """AC-extraction.1808.3 AC-extraction.1808.6: AC18.8.3 AC18.8.6 AC18.8.7: Statement posting records extracted->ledger entry->ledger line lineage."""
    _, _, txn, entry = await _seed_approved_statement_with_posted_txn(
        db,
        test_user.id,
        "DBS Evidence Graph Posting",
        txn_date=date(2025, 1, 21),
        description="Evidence graph salary",
        direction="IN",
        intent=EconomicIntent.INCOME,
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    await db.commit()

    assert entry.source_type == JournalEntrySourceType.AUTO_PARSED
    assert entry.source_id == txn.id

    # Statement->ledger lineage is materialized lazily; trigger it for the posted entry.
    from src.extraction.extension.evidence_graph_materialization import EvidenceGraphMaterializationService

    await EvidenceGraphMaterializationService().materialize_for_entity(
        db,
        user_id=test_user.id,
        entity_type="journal_entry",
        entity_id=entry.id,
    )
    await db.commit()

    nodes = {
        (node.node_kind, node.entity_type, node.entity_id): node
        for node in (await db.execute(select(EvidenceNode).where(EvidenceNode.user_id == test_user.id))).scalars()
    }
    extracted_node = nodes[("atomic_fact", "atomic_transaction", txn.id)]
    ledger_entry_node = nodes[("ledger_entry", "journal_entry", entry.id)]
    ledger_line_nodes = [nodes[("ledger_line", "journal_line", line.id)] for line in entry.lines]

    edges = {
        (edge.from_node_id, edge.to_node_id, edge.relation)
        for edge in (await db.execute(select(EvidenceEdge).where(EvidenceEdge.user_id == test_user.id))).scalars()
    }
    assert (extracted_node.id, ledger_entry_node.id, "posted_as") in edges
    assert {(ledger_entry_node.id, ledger_line_node.id, "contains") for ledger_line_node in ledger_line_nodes} <= edges


async def test_batch_approve_matches_returns_400_on_amount_mismatch(db, test_user):
    """AC16.24.4: Batch approval preserves acceptance amount validation failures."""
    account, statement, txn, _ = await _seed_approved_statement_with_posted_txn(
        db,
        test_user.id,
        "DBS Batch Mismatch",
        txn_date=date(2025, 1, 19),
        description="Mismatched payment",
    )
    entry_source_txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 19),
        description="Different payment",
        amount=Decimal("100.00"),
        direction="OUT",
    )
    db.add(entry_source_txn)
    await db.commit()
    await db.refresh(entry_source_txn)

    decision, counter_account, source_decision, trace_emitter = await anchored_reviewed_posting_inputs(
        db,
        user_id=test_user.id,
        transaction=entry_source_txn,
        intent=EconomicIntent.EXPENSE,
    )
    entry = await create_entry_from_txn(
        db,
        entry_source_txn,
        user_id=test_user.id,
        auto_post=True,
        disposition=decision,
        counter_account=counter_account,
        source_decision=source_decision,
        trace_emitter=trace_emitter,
    )
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await review_router.batch_approve_matches(
            request=BatchApproveRequest(match_ids=[match.id]),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value.status_code == 400
    assert "Amount mismatch" in exc_info.value.detail


async def test_batch_reject_matches_empty_list(db, test_user):
    """Given empty match_ids,
    When batch_reject_matches is called,
    Then it returns success with 0 rejected (line 1003-1004).
    """
    result = await review_router.batch_reject_matches(
        request=BatchRejectRequest(match_ids=[]),
        db=db,
        user_id=test_user.id,
    )
    assert result.rejected_count == 0


async def test_batch_reject_matches_success(db, test_user):
    """Given pending-review matches,
    When batch_reject_matches is called with match IDs,
    Then it rejects all matching records (lines 1006-1029).
    """
    from src.reconciliation import ReconciliationMatch, ReconciliationStatus

    _, _, txn = await _seed_approved_statement_with_txn(db, test_user.id, "DBS Batch Reject")

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        match_score=70,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)
    match_id = match.id

    result = await review_router.batch_reject_matches(
        request=BatchRejectRequest(match_ids=[match_id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.rejected_count == 1
