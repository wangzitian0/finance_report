"""Tests for get_reconciliation_stats function."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.services.reconciliation import get_reconciliation_stats


async def test_get_reconciliation_stats_basic(db):
    """Test basic reconciliation stats with various transaction states."""
    # Create user and account
    user_id = uuid4()
    account = Account(
        user_id=user_id,
        name="Test Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    # Create bank statement
    statement = BankStatement(
        user_id=user_id,
        account_id=account.id,
        file_path="test.pdf",
        file_hash="test_hash",
        original_filename="test.pdf",
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("0"),
        closing_balance=Decimal("0"),
    )
    db.add(statement)
    await db.flush()

    # Create transactions with different statuses
    txn1 = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 15),
        description="Salary",
        amount=Decimal("5000"),
        direction="IN",
        status=BankStatementTransactionStatus.MATCHED,
    )
    txn2 = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 16),
        description="Groceries",
        amount=Decimal("100"),
        direction="OUT",
        status=BankStatementTransactionStatus.UNMATCHED,
    )
    txn3 = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 17),
        description="Rent",
        amount=Decimal("2000"),
        direction="OUT",
        status=BankStatementTransactionStatus.MATCHED,
    )
    db.add_all([txn1, txn2, txn3])
    await db.flush()

    # Create matches with different statuses
    match1 = ReconciliationMatch(
        bank_txn_id=txn1.id,
        journal_entry_ids=[str(uuid4())],
        match_score=95,
        score_breakdown={"amount": 100.0, "date": 100.0},
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    match2 = ReconciliationMatch(
        bank_txn_id=txn3.id,
        journal_entry_ids=[str(uuid4())],
        match_score=70,
        score_breakdown={"amount": 90.0, "date": 80.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add_all([match1, match2])
    await db.flush()

    # Get stats
    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    # Verify basic counts
    assert stats.total_transactions == 3
    assert stats.matched_transactions == 2
    assert stats.unmatched_transactions == 1
    assert stats.pending_review == 1
    assert stats.auto_accepted == 1

    # Verify match rate calculation
    assert stats.match_rate == pytest.approx(66.67, rel=0.01)

    # Verify score distribution is None when not requested
    assert stats.score_distribution is None


async def test_get_reconciliation_stats_zero_division(db):
    """Test that zero division is handled when there are no transactions."""
    user_id = uuid4()

    # Get stats for user with no data
    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    # Verify all counts are zero
    assert stats.total_transactions == 0
    assert stats.matched_transactions == 0
    assert stats.unmatched_transactions == 0
    assert stats.pending_review == 0
    assert stats.auto_accepted == 0

    # Verify match rate is 0.0 (not NaN or error)
    assert stats.match_rate == 0.0

    # Verify score distribution is None when not requested
    assert stats.score_distribution is None


async def test_get_reconciliation_stats_without_distribution(db):
    """Test that stats work correctly without score distribution."""
    user_id = uuid4()
    account = Account(
        user_id=user_id,
        name="Test Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    statement = BankStatement(
        user_id=user_id,
        account_id=account.id,
        file_path="test.pdf",
        file_hash="test_hash",
        original_filename="test.pdf",
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("0"),
        closing_balance=Decimal("0"),
    )
    db.add(statement)
    await db.flush()

    # Create single transaction and match
    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 15),
        description="Test",
        amount=Decimal("100"),
        direction="IN",
        status=BankStatementTransactionStatus.MATCHED,
    )
    db.add(txn)
    await db.flush()

    match = ReconciliationMatch(
        bank_txn_id=txn.id,
        journal_entry_ids=[str(uuid4())],
        match_score=85,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    db.add(match)
    await db.flush()

    # Get stats without distribution
    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    # Verify basic stats
    assert stats.total_transactions == 1
    assert stats.matched_transactions == 1
    assert stats.auto_accepted == 1

    # Verify score distribution is None
    assert stats.score_distribution is None


async def test_get_reconciliation_stats_with_distribution(db):
    """Test score distribution bucketing with various scores."""
    user_id = uuid4()
    account = Account(
        user_id=user_id,
        name="Test Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    statement = BankStatement(
        user_id=user_id,
        account_id=account.id,
        file_path="test.pdf",
        file_hash="test_hash",
        original_filename="test.pdf",
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("0"),
        closing_balance=Decimal("0"),
    )
    db.add(statement)
    await db.flush()

    # Create 10 transactions with matches at different score ranges
    transactions = []
    for i, score in enumerate([50, 55, 65, 70, 75, 85, 88, 92, 95, 100]):
        txn = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date(2024, 1, 1 + i),
            description=f"Test {i}",
            amount=Decimal(str(100 + i)),
            direction="IN",
            status=BankStatementTransactionStatus.MATCHED,
        )
        transactions.append(txn)
    db.add_all(transactions)
    await db.commit()
    # Now create matches after transactions have IDs
    matches = []
    for txn, score in zip(transactions, [50, 55, 65, 70, 75, 85, 88, 92, 95, 100]):
        match = ReconciliationMatch(
            bank_txn_id=txn.id,
            journal_entry_ids=[str(uuid4())],
            match_score=score,
            score_breakdown={"amount": 100.0, "date": 100.0},
            status=ReconciliationStatus.AUTO_ACCEPTED,
        )
        matches.append(match)
    db.add_all(matches)
    await db.commit()

    # Get stats with distribution
    stats = await get_reconciliation_stats(db, user_id, include_distribution=True)

    # Verify score distribution buckets
    assert stats.score_distribution is not None
    assert stats.score_distribution["0-59"] == 2  # 50, 55
    assert stats.score_distribution["60-79"] == 3  # 65, 70, 75
    assert stats.score_distribution["80-89"] == 2  # 85, 88
    assert stats.score_distribution["90-100"] == 3  # 92, 95, 100
    total_scored = sum(stats.score_distribution.values())
    assert total_scored == 10
