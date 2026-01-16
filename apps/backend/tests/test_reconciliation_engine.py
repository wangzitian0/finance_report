"""Tests for reconciliation engine and review queue."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Account,
    AccountEvent,
    AccountType,
    BankTransactionStatus,
    ConfidenceLevel,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
    Statement,
    User,
)
from src.services.accounting import validate_journal_balance
from src.services.anomaly import detect_anomalies
from src.services.reconciliation import (
    DEFAULT_CONFIG,
    auto_accept,
    build_many_to_one_groups,
    execute_matching,
    normalize_text,
)
from src.services.review_queue import (
    accept_match,
    batch_accept,
    create_entry_from_txn,
    get_or_create_account,
    reject_match,
)


def _make_statement(*, owner_id: UUID | None = None, base_date: date) -> Statement:
    # Use uuid4 if owner_id not provided (for NOT NULL constraint)
    user_id = owner_id if owner_id else uuid4()
    return Statement(
        user_id=user_id,
        file_path="statements/test.pdf",
        file_hash="test_hash_" + str(base_date),  # Required NOT NULL field
        original_filename="test.pdf",
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=base_date,
        period_end=base_date,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )


def test_auto_accept_threshold() -> None:
    """Auto-accept helper respects the threshold."""
    assert auto_accept(DEFAULT_CONFIG.auto_accept, DEFAULT_CONFIG)
    assert not auto_accept(DEFAULT_CONFIG.pending_review - 1, DEFAULT_CONFIG)


def test_normalize_text_and_grouping() -> None:
    """Normalize text and group batch-like transactions."""
    assert normalize_text("  ACME-CO.  ") == "acme co"

    txn_date = date(2024, 2, 10)
    txn_a = AccountEvent(
        statement_id=uuid4(),
        txn_date=txn_date,
        description="Batch settlement ACME",
        amount=Decimal("12.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_b = AccountEvent(
        statement_id=uuid4(),
        txn_date=txn_date,
        description="Batch settlement ACME",
        amount=Decimal("18.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )

    groups = build_many_to_one_groups([txn_a, txn_b])
    assert len(groups) == 1
    assert len(groups[0]) == 2


async def test_execute_matching_auto_accepts_exact_match(db: AsyncSession) -> None:
    """Exact matches should be auto-accepted and reconciled."""
    user_id = uuid4()
    user = User(id=user_id, email="auto@example.com", hashed_password="hashed")
    bank = Account(
        user_id=user_id,
        name="Bank - Main",
        type=AccountType.ASSET,
        currency="SGD",
    )
    income = Account(
        user_id=user_id,
        name="Income - Salary",
        type=AccountType.INCOME,
        currency="SGD",
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 15),
        memo="Salary Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 1, 15))

    db.add_all([user, bank, income, entry, statement])
    await db.flush()

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.DEBIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=income.id,
        direction=Direction.CREDIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    txn = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 1, 15),
        description="Salary Payment",
        amount=Decimal("1000.00"),
        direction="IN",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add_all([line_debit, line_credit, txn])
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 1
    match = matches[0]
    assert match.status == ReconciliationStatus.AUTO_ACCEPTED
    assert str(entry.id) in match.journal_entry_ids

    await db.refresh(txn)
    await db.refresh(entry)
    assert txn.status == BankTransactionStatus.MATCHED
    assert entry.status == JournalEntryStatus.RECONCILED


async def test_execute_matching_pending_review_and_unmatched(db: AsyncSession) -> None:
    """Pending review and unmatched cases are handled correctly."""
    user_id = uuid4()
    user = User(id=user_id, email="pending@example.com", hashed_password="hashed")
    bank = Account(
        user_id=user_id,
        name="Bank - Alt",
        type=AccountType.ASSET,
        currency="SGD",
    )
    holding = Account(
        user_id=user_id,
        name="Holding - Asset",
        type=AccountType.ASSET,
        currency="SGD",
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 2, 5),
        memo="Transfer",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 2, 10))

    db.add_all([user, bank, holding, entry, statement])
    await db.flush()

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.DEBIT,
        amount=Decimal("96.00"),
        currency="SGD",
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=holding.id,
        direction=Direction.CREDIT,
        amount=Decimal("96.00"),
        currency="SGD",
    )
    txn_pending = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 2, 10),
        description="Transfer",
        amount=Decimal("100.00"),
        direction="IN",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.MEDIUM,
    )
    txn_unmatched = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2023, 12, 15),
        description="Old Vendor",
        amount=Decimal("45.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.LOW,
    )
    db.add_all([line_debit, line_credit, txn_pending, txn_unmatched])
    await db.commit()

    matches = await execute_matching(db, statement_id=statement.id, user_id=user_id)
    assert len(matches) == 1
    assert matches[0].status == ReconciliationStatus.PENDING_REVIEW

    await db.refresh(txn_pending)
    await db.refresh(txn_unmatched)
    assert txn_pending.status == BankTransactionStatus.PENDING
    assert txn_unmatched.status == BankTransactionStatus.UNMATCHED


async def test_execute_matching_many_to_one_group(db: AsyncSession) -> None:
    """Batch-like transactions should reconcile via many-to-one grouping."""
    user_id = uuid4()
    user = User(id=user_id, email="batch@example.com", hashed_password="hashed")
    bank = Account(
        user_id=user_id,
        name="Bank - Batch",
        type=AccountType.ASSET,
        currency="SGD",
    )
    expense = Account(
        user_id=user_id,
        name="Expense - Batch",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 1),
        memo="Batch settlement ACME",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 4, 1))

    db.add_all([user, bank, expense, entry, statement])
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )

    txn_a = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 4, 1),
        description="Batch settlement ACME",
        amount=Decimal("40.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_b = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 4, 1),
        description="Batch settlement ACME",
        amount=Decimal("60.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add_all([txn_a, txn_b])
    await db.commit()

    matches = await execute_matching(db, statement_id=statement.id, user_id=user_id)
    assert len(matches) == 2
    assert all(match.status == ReconciliationStatus.AUTO_ACCEPTED for match in matches)

    await db.refresh(txn_a)
    await db.refresh(txn_b)
    await db.refresh(entry)
    assert txn_a.status == BankTransactionStatus.MATCHED
    assert txn_b.status == BankTransactionStatus.MATCHED
    assert entry.status == JournalEntryStatus.RECONCILED


async def test_execute_matching_multi_entry_combinations(db: AsyncSession) -> None:
    """Multi-entry combinations should produce the best match."""
    user_id = uuid4()
    user = User(id=user_id, email="multi@example.com", hashed_password="hashed")
    bank = Account(
        user_id=user_id,
        name="Bank - Multi",
        type=AccountType.ASSET,
        currency="SGD",
    )
    expense = Account(
        user_id=user_id,
        name="Expense - Multi",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 4, 5))

    entry_a = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 5),
        memo="Split Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_b = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 5),
        memo="Split Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_c = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 5),
        memo="Split Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )

    db.add_all([user, bank, expense, statement, entry_a, entry_b, entry_c])
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_a.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("40.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_a.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("40.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_b.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_b.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_c.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_c.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
        ]
    )

    txn = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 4, 5),
        description="Split Payment",
        amount=Decimal("100.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add(txn)
    await db.commit()

    matches = await execute_matching(db, statement_id=statement.id, user_id=user_id)
    assert len(matches) == 1
    match = matches[0]
    assert match.status == ReconciliationStatus.AUTO_ACCEPTED
    assert match.score_breakdown.get("multi_entry") == 2

    await db.refresh(txn)
    assert txn.status == BankTransactionStatus.MATCHED


async def test_review_queue_error_paths(db: AsyncSession) -> None:
    """Review queue helpers raise on missing matches and handle empty batch."""
    with pytest.raises(ValueError, match="Match not found"):
        await accept_match(db, str(uuid4()), user_id=uuid4())
    with pytest.raises(ValueError, match="Match not found"):
        await reject_match(db, str(uuid4()), user_id=uuid4())
    assert await batch_accept(db, [], user_id=uuid4()) == []


async def test_get_or_create_account_reuses_existing(db: AsyncSession) -> None:
    """get_or_create_account returns existing records."""
    user_id = uuid4()
    account = await get_or_create_account(
        db,
        name="Bank - Main",
        account_type=AccountType.ASSET,
        currency="SGD",
        user_id=user_id,
    )
    account_again = await get_or_create_account(
        db,
        name="Bank - Main",
        account_type=AccountType.ASSET,
        currency="SGD",
        user_id=user_id,
    )
    assert account_again.id == account.id


async def test_create_entry_from_txn_inflow_uses_statement_currency(
    db: AsyncSession,
) -> None:
    """Inflow transactions use statement currency and income account."""
    user_id = uuid4()
    statement = Statement(
        user_id=user_id,
        account_id=None,
        file_path="statements/inflow.pdf",
        file_hash="hash_inflow",
        original_filename="inflow.pdf",
        institution="Test Bank",
        account_last4="2222",
        currency="USD",
        period_start=date(2024, 4, 10),
        period_end=date(2024, 4, 10),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    db.add(statement)
    await db.flush()

    txn = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 4, 10),
        description="Client deposit",
        amount=Decimal("250.00"),
        direction="IN",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add(txn)
    await db.commit()

    entry = await create_entry_from_txn(db, txn, user_id=user_id)
    assert entry.source_type == JournalEntrySourceType.BANK_STATEMENT
    assert all(line.currency == "USD" for line in entry.lines)

    result = await db.execute(select(Account).where(Account.name == "Income - Uncategorized"))
    assert result.scalar_one_or_none() is not None


async def test_review_queue_actions_and_entry_creation(db: AsyncSession) -> None:
    """Review queue operations update match and transaction status."""
    user_id = uuid4()
    user = User(
        id=user_id,
        email="default@example.com",
        hashed_password="hashed",
    )
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 3, 1))
    db.add_all([user, statement])
    await db.flush()

    txn_accept = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 3, 1),
        description="Coffee",
        amount=Decimal("12.34"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_reject = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 3, 1),
        description="Snacks",
        amount=Decimal("5.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_batch = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 3, 1),
        description="Lunch",
        amount=Decimal("15.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add_all([txn_accept, txn_reject, txn_batch])
    await db.commit()

    entry_accept = await create_entry_from_txn(db, txn_accept, user_id=user_id)
    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_accept.id)
        .options(selectinload(JournalEntry.lines))
    )
    entry_accept = entry_result.scalar_one()
    validate_journal_balance(entry_accept.lines)

    accounts_result = await db.execute(select(Account).where(Account.user_id == user_id))
    accounts = {account.name: account for account in accounts_result.scalars().all()}
    bank = accounts["Bank - Main"]
    expense = accounts["Expense - Uncategorized"]

    entry_reject = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 3, 1),
        memo="Reject entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_batch = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 3, 1),
        memo="Batch entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([entry_reject, entry_batch])
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_reject.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("5.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_reject.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("5.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_batch.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("15.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_batch.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("15.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    match_accept = ReconciliationMatch(
        bank_txn_id=txn_accept.id,
        journal_entry_ids=[str(entry_accept.id)],
        match_score=92,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_reject = ReconciliationMatch(
        bank_txn_id=txn_reject.id,
        journal_entry_ids=[str(entry_reject.id)],
        match_score=55,
        score_breakdown={"amount": 70.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_batch = ReconciliationMatch(
        bank_txn_id=txn_batch.id,
        journal_entry_ids=[str(entry_batch.id)],
        match_score=85,
        score_breakdown={"amount": 90.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add_all([match_accept, match_reject, match_batch])
    await db.commit()

    accepted = await accept_match(db, str(match_accept.id), user_id=user_id)
    rejected = await reject_match(db, str(match_reject.id), user_id=user_id)
    batch = await batch_accept(db, [str(match_batch.id)], user_id=user_id)

    assert accepted.status == ReconciliationStatus.ACCEPTED
    assert rejected.status == ReconciliationStatus.REJECTED
    assert len(batch) == 1
    assert batch[0].status == ReconciliationStatus.ACCEPTED

    await db.refresh(txn_accept)
    await db.refresh(txn_reject)
    await db.refresh(txn_batch)
    await db.refresh(entry_accept)
    assert txn_accept.status == BankTransactionStatus.MATCHED
    assert txn_reject.status == BankTransactionStatus.UNMATCHED
    assert txn_batch.status == BankTransactionStatus.MATCHED
    assert entry_accept.status == JournalEntryStatus.RECONCILED


async def test_detect_anomalies_flags_expected_patterns(db: AsyncSession) -> None:
    """Anomaly detection flags large, frequent, and new merchants."""
    user_id = uuid4()
    statement = _make_statement(owner_id=user_id, base_date=date(2024, 3, 4))
    db.add(statement)
    await db.flush()

    history_events = [
        AccountEvent(
            statement_id=statement.id,
            txn_date=date(2024, 3, 4),
            description="Coffee Shop",
            amount=Decimal("10.00"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
            confidence=ConfidenceLevel.HIGH,
        )
        for _ in range(6)
    ]
    db.add_all(history_events)
    await db.commit()

    txn_large = AccountEvent(
        statement_id=statement.id,
        txn_date=date(2024, 3, 4),
        description="Coffee Shop",
        amount=Decimal("200.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    anomalies_large = await detect_anomalies(db, txn_large, user_id=user_id)
    anomaly_types = {item.anomaly_type for item in anomalies_large}
    assert "LARGE_AMOUNT" in anomaly_types
    assert "FREQUENCY_SPIKE" in anomaly_types

    # 2024-03-09 is Saturday. Fixed date chosen to ensure stable weekend detection
    # across all timezones (no date arithmetic that could shift days).
    weekend_date = date(2024, 3, 9)
    txn_weekend = AccountEvent(
        statement_id=statement.id,
        txn_date=weekend_date,
        description="Gift Shop",
        amount=Decimal("60.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    anomalies_weekend = await detect_anomalies(db, txn_weekend, user_id=user_id)
    weekend_types = {item.anomaly_type for item in anomalies_weekend}
    assert "NEW_MERCHANT" in weekend_types
    assert "WEEKEND_LARGE" in weekend_types
