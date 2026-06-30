"""Additional coverage for reconciliation router helpers."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import PaginationParams
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.models.statement_summary import StatementSummary
from src.routers import reconciliation as reconciliation_router
from src.schemas.reconciliation import (
    BatchAcceptRequest,
    ReconciliationRunRequest,
    ReconciliationStatusEnum,
)
from tests.factories import UserFactory


async def _create_statement(db: AsyncSession, user_id, account_id=None) -> StatementSummary:
    """Create a StatementSummary conform linked to an ODS UploadedDocument.

    Atomic transactions reference the document via ``source_documents`` so the
    router can resolve a statement's transactions and custody account.
    """
    today = date.today()
    file_hash = str(uuid4())
    doc = UploadedDocument(
        user_id=user_id,
        file_path="statements/test.pdf",
        file_hash=file_hash,
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    statement = StatementSummary(
        user_id=user_id,
        account_id=account_id,
        uploaded_document_id=doc.id,
        file_hash=file_hash,
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=today,
        period_end=today,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    db.add(statement)
    await db.flush()
    return statement


async def _create_transaction(
    db: AsyncSession,
    statement: StatementSummary,
    *,
    amount: Decimal,
    status=None,
) -> AtomicTransaction:
    """Create an AtomicTransaction owned by the given statement conform.

    ``status`` is accepted for call-site compatibility but ignored: atomic
    transactions have no per-row status (match status is the source of truth).
    """
    txn = AtomicTransaction(
        user_id=statement.user_id,
        txn_date=date.today(),
        description="Test txn",
        amount=amount,
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(statement.uploaded_document_id), "doc_type": "bank_statement"}],
    )
    db.add(txn)
    await db.flush()
    return txn


async def test_build_match_response_includes_entries(db: AsyncSession, test_user) -> None:
    asset = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([asset, income])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Test entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=asset.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("100.00"), status=None)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        score_breakdown={"amount": 90.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)

    # Load entry summaries the same way the router does
    entry_summaries = await reconciliation_router._load_entry_summaries(db, [match], test_user.id)
    response = reconciliation_router._build_match_response(
        match,
        transaction=txn,
        entry_summaries=entry_summaries,
    )

    assert response.transaction is not None
    assert len(response.entries) == 1
    assert response.entries[0].total_amount == Decimal("100.00")
    # Verify entry summary structure as per CR feedback
    assert response.entries[0].entry_date == entry.entry_date
    assert response.entries[0].memo == "Test entry"
    assert response.entries[0].id == entry.id


async def test_run_reconciliation_statement_not_found(db: AsyncSession, test_user) -> None:
    payload = ReconciliationRunRequest(statement_id=uuid4())
    with pytest.raises(HTTPException, match="Statement not found"):
        await reconciliation_router.run_reconciliation(payload, db, test_user.id)


async def test_run_reconciliation_filters_unmatched(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    statement = await _create_statement(db, test_user.id)
    await _create_transaction(db, statement, amount=Decimal("5.00"), status=None)
    await db.commit()

    async def fake_execute_matching(*_args, **_kwargs):
        return [
            ReconciliationMatch(
                atomic_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.AUTO_ACCEPTED,
            ),
            ReconciliationMatch(
                atomic_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=70,
                score_breakdown={},
                status=ReconciliationStatus.PENDING_REVIEW,
            ),
        ]

    monkeypatch.setattr(reconciliation_router, "execute_matching", fake_execute_matching)

    response = await reconciliation_router.run_reconciliation(
        ReconciliationRunRequest(statement_id=statement.id), db, test_user.id
    )

    assert response.matches_created == 2
    assert response.auto_accepted == 1
    assert response.pending_review == 1
    assert response.unmatched == 1


async def test_AC10_8_3_reconciliation_run_audit_checkpoints(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-observability.8.3: Reconciliation run logs start/completion/failure replay checkpoints."""
    statement = await _create_statement(db, test_user.id)
    statement_id = statement.id
    await _create_transaction(db, statement, amount=Decimal("5.00"), status=None)
    await db.commit()

    async def fake_execute_matching(*_args, **_kwargs):
        return [
            ReconciliationMatch(
                atomic_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.AUTO_ACCEPTED,
            )
        ]

    mock_info = MagicMock()
    mock_exception = MagicMock()
    monkeypatch.setattr(reconciliation_router, "execute_matching", fake_execute_matching)
    monkeypatch.setattr(reconciliation_router.logger, "info", mock_info)
    monkeypatch.setattr(reconciliation_router.logger, "exception", mock_exception)

    response = await reconciliation_router.run_reconciliation(
        ReconciliationRunRequest(statement_id=statement_id, limit=25), db, test_user.id
    )

    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    started = next(kwargs for event, kwargs in calls if event == "reconciliation.run.started")
    completed = next(kwargs for event, kwargs in calls if event == "reconciliation.run.completed")

    assert response.matches_created == 1
    assert started["audit_event"] == "reconciliation.run.started"
    assert started["request_id"]
    assert started["statement_id"] == str(statement_id)
    assert started["phase"] == "matching_started"
    assert started["progress"] is None
    assert started["model_to_use"] is None
    assert started["limit"] == 25
    assert completed["audit_event"] == "reconciliation.run.completed"
    assert completed["request_id"] == started["request_id"]
    assert completed["statement_id"] == str(statement_id)
    assert completed["phase"] == "matching_completed"
    assert completed["progress"] is None
    assert completed["model_to_use"] is None
    assert completed["matches_created"] == 1
    assert completed["auto_accepted"] == 1
    assert completed["pending_review"] == 0
    assert completed["unmatched"] == 1

    async def fail_execute_matching(*_args, **_kwargs):
        raise RuntimeError("matching score service unavailable with raw details omitted")

    monkeypatch.setattr(reconciliation_router, "execute_matching", fail_execute_matching)

    with pytest.raises(RuntimeError, match="matching score service unavailable"):
        await reconciliation_router.run_reconciliation(
            ReconciliationRunRequest(statement_id=statement_id, limit=25), db, test_user.id
        )

    failed = next(call.kwargs for call in mock_exception.call_args_list if call.args[0] == "reconciliation.run.failed")
    assert failed["audit_event"] == "reconciliation.run.failed"
    assert failed["statement_id"] == str(statement_id)
    assert failed["phase"] == "matching_failed"
    assert failed["progress"] is None
    assert failed["model_to_use"] is None
    assert failed["limit"] == 25
    assert failed["error_type"] == "RuntimeError"
    assert failed["safe_error_message"] == "matching score service unavailable with raw details omitted"


async def test_list_matches_filters_by_status(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_pending = await _create_transaction(db, statement, amount=Decimal("8.00"), status=None)
    txn_accept = await _create_transaction(db, statement, amount=Decimal("9.00"), status=None)
    db.add_all(
        [
            ReconciliationMatch(
                atomic_txn_id=txn_pending.id,
                journal_entry_ids=[],
                match_score=70,
                score_breakdown={},
                status=ReconciliationStatus.PENDING_REVIEW,
            ),
            ReconciliationMatch(
                atomic_txn_id=txn_accept.id,
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.ACCEPTED,
            ),
        ]
    )
    await db.commit()

    from src.routers import reconciliation as reconciliation_router

    response = await reconciliation_router.list_matches(
        status_filter=ReconciliationStatusEnum.PENDING_REVIEW,
        limit=50,
        offset=0,
        db=db,
        user_id=test_user.id,
    )

    assert response.total == 1
    assert response.items[0].status == ReconciliationStatusEnum.PENDING_REVIEW


async def test_load_entry_summaries_empty(db: AsyncSession, test_user) -> None:
    """Test _load_entry_summaries with empty input."""
    from src.routers.reconciliation import _load_entry_summaries

    result = await _load_entry_summaries(db, [], test_user.id)
    assert result == {}


async def test_load_entry_summaries_invalid_uuid(db: AsyncSession, test_user) -> None:
    """Test _load_entry_summaries with invalid UUID strings."""
    from src.models.reconciliation import ReconciliationMatch
    from src.routers.reconciliation import _load_entry_summaries

    match = ReconciliationMatch(
        atomic_txn_id=uuid4(),
        journal_entry_ids=["not-a-uuid"],
        match_score=80,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    result = await _load_entry_summaries(db, [match], test_user.id)
    assert result == {}


async def test_reconciliation_stats_bucket_distribution(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_scores = [
        (Decimal("10.00"), None, 55),
        (Decimal("11.00"), None, 70),
        (Decimal("12.00"), None, 85),
        (Decimal("13.00"), None, 95),
    ]
    matches = []
    for amount, _status, score in txn_scores:
        txn = await _create_transaction(db, statement, amount=amount, status=None)
        # Two highest-scoring matches are auto-accepted (counted as matched); the
        # lower two stay pending. There is no per-transaction status column.
        matches.append(
            ReconciliationMatch(
                atomic_txn_id=txn.id,
                journal_entry_ids=[],
                match_score=score,
                score_breakdown={},
                status=(ReconciliationStatus.AUTO_ACCEPTED if score >= 80 else ReconciliationStatus.PENDING_REVIEW),
            )
        )
    db.add_all(matches)
    await db.commit()

    stats = await reconciliation_router.reconciliation_stats(db=db, user_id=test_user.id)

    assert stats.total_transactions == 4
    assert stats.matched_transactions == 2
    assert stats.match_rate == 50.0
    assert stats.score_distribution["0-59"] == 1
    assert stats.score_distribution["60-79"] == 1
    assert stats.score_distribution["80-89"] == 1
    assert stats.score_distribution["90-100"] == 1


async def test_pending_review_queue_returns_items(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("6.00"), status=None)
    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[],
            match_score=80,
            score_breakdown={},
            status=ReconciliationStatus.PENDING_REVIEW,
        )
    )
    await db.commit()

    response = await reconciliation_router.pending_review_queue(limit=50, offset=0, db=db, user_id=test_user.id)

    assert response.total == 1
    assert response.items[0].status == ReconciliationStatusEnum.PENDING_REVIEW


async def test_accept_reject_batch_accept(db: AsyncSession, test_user) -> None:
    """[AC4.3.3] Test batch accept functionality."""
    account = Account(
        user_id=test_user.id, name="Mapped Reconciliation Account", type=AccountType.ASSET, currency="SGD"
    )
    db.add(account)
    await db.flush()
    statement = await _create_statement(db, test_user.id, account_id=account.id)
    txn_accept = await _create_transaction(db, statement, amount=Decimal("7.00"), status=None)
    txn_reject = await _create_transaction(db, statement, amount=Decimal("8.00"), status=None)
    txn_batch = await _create_transaction(db, statement, amount=Decimal("9.00"), status=None)
    match_accept = ReconciliationMatch(
        atomic_txn_id=txn_accept.id,
        journal_entry_ids=[],
        match_score=85,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_reject = ReconciliationMatch(
        atomic_txn_id=txn_reject.id,
        journal_entry_ids=[],
        match_score=75,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_batch = ReconciliationMatch(
        atomic_txn_id=txn_batch.id,
        journal_entry_ids=[],
        match_score=90,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add_all([match_accept, match_reject, match_batch])
    await db.commit()

    accepted = await reconciliation_router.accept_match(match_id=str(match_accept.id), db=db, user_id=test_user.id)
    rejected = await reconciliation_router.reject_match(match_id=str(match_reject.id), db=db, user_id=test_user.id)
    batch = await reconciliation_router.batch_accept(
        payload=BatchAcceptRequest(match_ids=[str(match_batch.id)]),
        db=db,
        user_id=test_user.id,
    )

    assert accepted.status == ReconciliationStatusEnum.ACCEPTED
    assert rejected.status == ReconciliationStatusEnum.REJECTED
    assert batch.total == 1


async def test_list_unmatched_and_create_entry(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("4.00"), status=None)
    await db.commit()

    unmatched = await reconciliation_router.list_unmatched(limit=50, offset=0, db=db, user_id=test_user.id)
    assert unmatched.total == 1

    entry = await reconciliation_router.create_entry(txn_id=str(txn.id), db=db, user_id=test_user.id)
    assert entry.total_amount == Decimal("4.00")


async def test_list_anomalies_returns_list(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("10.00"), status=None)
    await db.commit()

    anomalies = await reconciliation_router.list_anomalies(
        txn_id=str(txn.id), db=db, user_id=test_user.id, pagination=PaginationParams()
    )
    assert isinstance(anomalies, list)


async def test_accept_match_already_accepted_is_idempotent(db: AsyncSession, test_user) -> None:
    """Accepting an already-accepted match should return it unchanged (idempotent)."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("15.00"), status=None)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=90,
        score_breakdown={},
        status=ReconciliationStatus.ACCEPTED,  # Already accepted
    )
    db.add(match)
    await db.commit()

    # Second accept should be idempotent
    result = await accept_match_service(db, str(match.id), user_id=test_user.id)

    assert result.status == ReconciliationStatus.ACCEPTED


async def test_reject_match_already_rejected_is_idempotent(db: AsyncSession, test_user) -> None:
    """Rejecting an already-rejected match should return it unchanged (idempotent)."""
    from src.services.review_queue import reject_match as reject_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("16.00"), status=None)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=60,
        score_breakdown={},
        status=ReconciliationStatus.REJECTED,  # Already rejected
    )
    db.add(match)
    await db.commit()

    # Second reject should be idempotent
    result = await reject_match_service(db, str(match.id), user_id=test_user.id)

    assert result.status == ReconciliationStatus.REJECTED


async def test_build_match_response_with_invalid_uuid_in_entry_ids(db: AsyncSession, test_user) -> None:
    """Invalid UUIDs in journal_entry_ids should be gracefully skipped."""
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("20.00"), status=None)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=["not-a-valid-uuid", "also-invalid"],  # Invalid UUIDs
        match_score=75,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()

    # Loading entry summaries should skip invalid UUIDs without crashing
    entry_summaries = await reconciliation_router._load_entry_summaries(db, [match], test_user.id)

    # Should return empty dict since no valid UUIDs
    assert entry_summaries == {}


async def test_accept_match_amount_mismatch_raises(db: AsyncSession, test_user) -> None:
    """Accept match should raise ValueError when entry amounts don't match transaction."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("100.00"), status=None)

    # Create a journal entry with mismatched amount
    account = Account(user_id=test_user.id, name="Test Account", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=txn.txn_date,
        memo="Test entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    # Entry amount is $50, but transaction is $100 - should fail validation
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("50.00"),
            currency="SGD",
        )
    )
    await db.flush()

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=80,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()

    with pytest.raises(ValueError, match="Amount mismatch"):
        await accept_match_service(db, str(match.id), user_id=test_user.id)


async def test_accept_match_amount_within_tolerance(db: AsyncSession, test_user) -> None:
    """Accept match should succeed when amounts match within tolerance."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("100.00"), status=None)

    account = Account(user_id=test_user.id, name="Test Account", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=txn.txn_date,
        memo="Test entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    # Entry amount is $99.95 - within 1% tolerance of $100
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("99.95"),
            currency="SGD",
        )
    )
    await db.flush()

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()

    result = await accept_match_service(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED


async def test_accept_match_skip_validation_bypasses_check(db: AsyncSession, test_user) -> None:
    """Accept match with skip_amount_validation=True should bypass validation."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(db, statement, amount=Decimal("100.00"), status=None)

    account = Account(user_id=test_user.id, name="Test Account", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=txn.txn_date,
        memo="Test entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    # Entry amount is $50, but we skip validation
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("50.00"),
            currency="SGD",
        )
    )
    await db.flush()

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=80,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()

    # Should succeed with skip_amount_validation=True
    result = await accept_match_service(db, str(match.id), user_id=test_user.id, skip_amount_validation=True)
    assert result.status == ReconciliationStatus.ACCEPTED


async def test_batch_accept_skips_low_score_matches(db: AsyncSession, test_user) -> None:
    """batch_accept should skip matches below min_score threshold."""
    from src.services.review_queue import batch_accept

    statement = await _create_statement(db, test_user.id)
    # Create a low-score match
    txn = await _create_transaction(db, statement, amount=Decimal("50.00"), status=None)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=60,  # Below default min_score of 75
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()

    # batch_accept with min_score=75 should skip this match
    accepted = await batch_accept(db, user_id=test_user.id, match_ids=[str(match.id)], min_score=75)

    # Should return empty since match was below threshold
    assert len(accepted) == 0

    # Verify match was not modified
    await db.refresh(match)
    assert match.status == ReconciliationStatus.PENDING_REVIEW


async def test_create_entry_from_txn_uses_statement_account(db: AsyncSession, test_user) -> None:
    """create_entry_from_txn should use statement's linked account when available."""
    from src.services.review_queue import create_entry_from_txn

    # Create a bank account to link to the statement
    bank_account = Account(
        user_id=test_user.id,
        name="Linked Bank Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank_account)
    await db.flush()

    # Create statement conform with linked account_id
    statement = await _create_statement(db, test_user.id, account_id=bank_account.id)

    txn = await _create_transaction(db, statement, amount=Decimal("100.00"), status=None)

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)

    # Verify entry uses the linked bank account
    assert entry is not None
    # Check that one of the lines uses the linked account
    account_ids = [line.account_id for line in entry.lines]
    assert bank_account.id in account_ids


async def test_create_entry_from_txn_rejects_other_user_transaction(db: AsyncSession, test_user) -> None:
    """create_entry_from_txn should reject transactions from other users."""
    from src.services.review_queue import create_entry_from_txn

    # Create a statement + transaction for a different user
    other_user_id = (await UserFactory.create_async(db)).id
    other_statement = await _create_statement(db, other_user_id)
    txn = await _create_transaction(db, other_statement, amount=Decimal("50.00"), status=None)
    await db.commit()

    # Should fail when test_user tries to create entry from other user's transaction
    with pytest.raises(ValueError, match="Transaction does not belong to user"):
        await create_entry_from_txn(db, txn, user_id=test_user.id)
