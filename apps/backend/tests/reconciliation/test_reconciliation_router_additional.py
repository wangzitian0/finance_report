"""Additional coverage for reconciliation router helpers."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    ConfidenceLevel,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.routers import reconciliation as reconciliation_router
from src.schemas.reconciliation import (
    BatchAcceptRequest,
    ReconciliationRunRequest,
    ReconciliationStatusEnum,
)


async def _create_statement(db: AsyncSession, user_id) -> BankStatement:
    today = date.today()
    statement = BankStatement(
        user_id=user_id,
        account_id=None,
        file_path="statements/test.pdf",
        file_hash=str(uuid4()),
        original_filename="test.pdf",
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
    statement_id,
    *,
    amount: Decimal,
    status: BankStatementTransactionStatus,
) -> BankStatementTransaction:
    txn = BankStatementTransaction(
        statement_id=statement_id,
        txn_date=date.today(),
        description="Test txn",
        amount=amount,
        direction="OUT",
        status=status,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add(txn)
    await db.flush()
    return txn


@pytest.mark.asyncio
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
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("100.00"), status=BankStatementTransactionStatus.PENDING
    )
    match = ReconciliationMatch(
        bank_txn_id=txn.id,
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


@pytest.mark.asyncio
async def test_run_reconciliation_statement_not_found(db: AsyncSession, test_user) -> None:
    payload = ReconciliationRunRequest(statement_id=uuid4())
    with pytest.raises(HTTPException, match="Statement not found"):
        await reconciliation_router.run_reconciliation(payload, db, test_user.id)


@pytest.mark.asyncio
async def test_run_reconciliation_filters_unmatched(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    statement = await _create_statement(db, test_user.id)
    await _create_transaction(db, statement.id, amount=Decimal("5.00"), status=BankStatementTransactionStatus.UNMATCHED)
    await db.commit()

    async def fake_execute_matching(*_args, **_kwargs):
        return [
            ReconciliationMatch(
                bank_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.AUTO_ACCEPTED,
            ),
            ReconciliationMatch(
                bank_txn_id=uuid4(),
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


@pytest.mark.asyncio
async def test_list_matches_filters_by_status(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_pending = await _create_transaction(
        db, statement.id, amount=Decimal("8.00"), status=BankStatementTransactionStatus.PENDING
    )
    txn_accept = await _create_transaction(
        db, statement.id, amount=Decimal("9.00"), status=BankStatementTransactionStatus.PENDING
    )
    db.add_all(
        [
            ReconciliationMatch(
                bank_txn_id=txn_pending.id,
                journal_entry_ids=[],
                match_score=70,
                score_breakdown={},
                status=ReconciliationStatus.PENDING_REVIEW,
            ),
            ReconciliationMatch(
                bank_txn_id=txn_accept.id,
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


@pytest.mark.asyncio
async def test_load_entry_summaries_empty(db: AsyncSession, test_user) -> None:
    """Test _load_entry_summaries with empty input."""
    from src.routers.reconciliation import _load_entry_summaries

    result = await _load_entry_summaries(db, [], test_user.id)
    assert result == {}


@pytest.mark.asyncio
async def test_load_entry_summaries_invalid_uuid(db: AsyncSession, test_user) -> None:
    """Test _load_entry_summaries with invalid UUID strings."""
    from src.models import ReconciliationMatch
    from src.routers.reconciliation import _load_entry_summaries

    match = ReconciliationMatch(
        bank_txn_id=uuid4(),
        journal_entry_ids=["not-a-uuid"],
        match_score=80,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    result = await _load_entry_summaries(db, [match], test_user.id)
    assert result == {}


@pytest.mark.asyncio
async def test_reconciliation_stats_bucket_distribution(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_scores = [
        (Decimal("10.00"), BankStatementTransactionStatus.MATCHED, 55),
        (Decimal("11.00"), BankStatementTransactionStatus.MATCHED, 70),
        (Decimal("12.00"), BankStatementTransactionStatus.UNMATCHED, 85),
        (Decimal("13.00"), BankStatementTransactionStatus.UNMATCHED, 95),
    ]
    matches = []
    for amount, status, score in txn_scores:
        txn = await _create_transaction(db, statement.id, amount=amount, status=status)
        matches.append(
            ReconciliationMatch(
                bank_txn_id=txn.id,
                journal_entry_ids=[],
                match_score=score,
                score_breakdown={},
                status=(ReconciliationStatus.PENDING_REVIEW if score < 90 else ReconciliationStatus.AUTO_ACCEPTED),
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


@pytest.mark.asyncio
async def test_pending_review_queue_returns_items(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("6.00"), status=BankStatementTransactionStatus.PENDING
    )
    db.add(
        ReconciliationMatch(
            bank_txn_id=txn.id,
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


@pytest.mark.asyncio
async def test_accept_reject_batch_accept(db: AsyncSession, test_user) -> None:
    """[AC4.3.3] Test batch accept functionality."""
    statement = await _create_statement(db, test_user.id)
    txn_accept = await _create_transaction(
        db, statement.id, amount=Decimal("7.00"), status=BankStatementTransactionStatus.PENDING
    )
    txn_reject = await _create_transaction(
        db, statement.id, amount=Decimal("8.00"), status=BankStatementTransactionStatus.PENDING
    )
    txn_batch = await _create_transaction(
        db, statement.id, amount=Decimal("9.00"), status=BankStatementTransactionStatus.PENDING
    )
    match_accept = ReconciliationMatch(
        bank_txn_id=txn_accept.id,
        journal_entry_ids=[],
        match_score=85,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_reject = ReconciliationMatch(
        bank_txn_id=txn_reject.id,
        journal_entry_ids=[],
        match_score=75,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_batch = ReconciliationMatch(
        bank_txn_id=txn_batch.id,
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


@pytest.mark.asyncio
async def test_list_unmatched_and_create_entry(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("4.00"), status=BankStatementTransactionStatus.UNMATCHED
    )
    await db.commit()

    unmatched = await reconciliation_router.list_unmatched(limit=50, offset=0, db=db, user_id=test_user.id)
    assert unmatched.total == 1

    entry = await reconciliation_router.create_entry(txn_id=str(txn.id), db=db, user_id=test_user.id)
    assert entry.total_amount == Decimal("4.00")


@pytest.mark.asyncio
async def test_list_anomalies_returns_list(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("10.00"), status=BankStatementTransactionStatus.PENDING
    )
    await db.commit()

    anomalies = await reconciliation_router.list_anomalies(txn_id=str(txn.id), db=db, user_id=test_user.id)
    assert isinstance(anomalies, list)


@pytest.mark.asyncio
async def test_accept_match_already_accepted_is_idempotent(db: AsyncSession, test_user) -> None:
    """Accepting an already-accepted match should return it unchanged (idempotent)."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("15.00"), status=BankStatementTransactionStatus.MATCHED
    )
    match = ReconciliationMatch(
        bank_txn_id=txn.id,
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


@pytest.mark.asyncio
async def test_reject_match_already_rejected_is_idempotent(db: AsyncSession, test_user) -> None:
    """Rejecting an already-rejected match should return it unchanged (idempotent)."""
    from src.services.review_queue import reject_match as reject_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("16.00"), status=BankStatementTransactionStatus.UNMATCHED
    )
    match = ReconciliationMatch(
        bank_txn_id=txn.id,
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


@pytest.mark.asyncio
async def test_build_match_response_with_invalid_uuid_in_entry_ids(db: AsyncSession, test_user) -> None:
    """Invalid UUIDs in journal_entry_ids should be gracefully skipped."""
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("20.00"), status=BankStatementTransactionStatus.PENDING
    )
    match = ReconciliationMatch(
        bank_txn_id=txn.id,
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


@pytest.mark.asyncio
async def test_accept_match_amount_mismatch_raises(db: AsyncSession, test_user) -> None:
    """Accept match should raise ValueError when entry amounts don't match transaction."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("100.00"), status=BankStatementTransactionStatus.PENDING
    )

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
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=80,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()

    with pytest.raises(ValueError, match="Amount mismatch"):
        await accept_match_service(db, str(match.id), user_id=test_user.id)


@pytest.mark.asyncio
async def test_accept_match_amount_within_tolerance(db: AsyncSession, test_user) -> None:
    """Accept match should succeed when amounts match within tolerance."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("100.00"), status=BankStatementTransactionStatus.PENDING
    )

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
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()

    result = await accept_match_service(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED


@pytest.mark.asyncio
async def test_accept_match_skip_validation_bypasses_check(db: AsyncSession, test_user) -> None:
    """Accept match with skip_amount_validation=True should bypass validation."""
    from src.services.review_queue import accept_match as accept_match_service

    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("100.00"), status=BankStatementTransactionStatus.PENDING
    )

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
        bank_txn_id=txn.id,
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


@pytest.mark.asyncio
async def test_batch_accept_skips_low_score_matches(db: AsyncSession, test_user) -> None:
    """batch_accept should skip matches below min_score threshold."""
    from src.services.review_queue import batch_accept

    statement = await _create_statement(db, test_user.id)
    # Create a low-score match
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("50.00"), status=BankStatementTransactionStatus.PENDING
    )
    match = ReconciliationMatch(
        bank_txn_id=txn.id,
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


@pytest.mark.asyncio
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

    # Create statement with linked account_id
    statement = BankStatement(
        user_id=test_user.id,
        file_path="test/path",
        file_hash="hash123",
        original_filename="test.pdf",
        institution="Test Bank",
        currency="SGD",
        period_start=date.today(),
        period_end=date.today(),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("900.00"),
        account_id=bank_account.id,  # Link the account
    )
    db.add(statement)
    await db.flush()

    txn = await _create_transaction(
        db, statement.id, amount=Decimal("100.00"), status=BankStatementTransactionStatus.UNMATCHED
    )

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)

    # Verify entry uses the linked bank account
    assert entry is not None
    # Check that one of the lines uses the linked account
    account_ids = [line.account_id for line in entry.lines]
    assert bank_account.id in account_ids


@pytest.mark.asyncio
async def test_create_entry_from_txn_rejects_other_user_transaction(db: AsyncSession, test_user) -> None:
    """create_entry_from_txn should reject transactions from other users."""
    from src.services.review_queue import create_entry_from_txn

    # Create a statement for a different user
    other_user_id = uuid4()
    other_statement = BankStatement(
        user_id=other_user_id,
        file_path="test/other",
        file_hash="other123",
        original_filename="other.pdf",
        institution="Other Bank",
        currency="SGD",
        period_start=date.today(),
        period_end=date.today(),
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("400.00"),
    )
    db.add(other_statement)
    await db.flush()

    txn = BankStatementTransaction(
        statement_id=other_statement.id,
        txn_date=date.today(),
        description="Other user txn",
        amount=Decimal("50.00"),
        direction="OUT",
        status=BankStatementTransactionStatus.UNMATCHED,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add(txn)
    await db.commit()

    # Should fail when test_user tries to create entry from other user's transaction
    with pytest.raises(ValueError, match="Transaction does not belong to user"):
        await create_entry_from_txn(db, txn, user_id=test_user.id)
