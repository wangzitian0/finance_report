"""Tests for get_reconciliation_stats function.

Stats are computed over Layer-2 ``AtomicTransaction`` rows and their
``ReconciliationMatch`` records (keyed on ``atomic_txn_id``). A transaction is
"matched" when it has an active accepted/auto-accepted match; "unmatched"
otherwise. There is no per-transaction status column.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.ledger import Account, AccountType
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, get_reconciliation_stats


def _make_atomic(user_id, *, txn_date, description, amount, direction=TransactionDirection.IN):
    return AtomicTransaction(
        user_id=user_id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
    )


async def test_get_reconciliation_stats_basic(db, test_user):
    """Test basic reconciliation stats with various match states."""
    user_id = test_user.id
    account = Account(
        user_id=user_id,
        name="Test Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    # Three atomic transactions
    txn1 = _make_atomic(user_id, txn_date=date(2024, 1, 15), description="Salary", amount=Decimal("5000"))
    txn2 = _make_atomic(
        user_id,
        txn_date=date(2024, 1, 16),
        description="Groceries",
        amount=Decimal("100"),
        direction=TransactionDirection.OUT,
    )
    txn3 = _make_atomic(
        user_id,
        txn_date=date(2024, 1, 17),
        description="Rent",
        amount=Decimal("2000"),
        direction=TransactionDirection.OUT,
    )
    db.add_all([txn1, txn2, txn3])
    await db.flush()

    # txn1 -> auto-accepted (counts as matched), txn3 -> pending (not matched)
    match1 = ReconciliationMatch(
        atomic_txn_id=txn1.id,
        journal_entry_ids=[str(uuid4())],
        match_score=95,
        score_breakdown={"amount": 100.0, "date": 100.0},
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    match2 = ReconciliationMatch(
        atomic_txn_id=txn3.id,
        journal_entry_ids=[str(uuid4())],
        match_score=70,
        score_breakdown={"amount": 90.0, "date": 80.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add_all([match1, match2])
    await db.flush()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    assert stats.total_transactions == 3
    # Only accepted/auto-accepted matches count as "matched".
    assert stats.matched_transactions == 1
    assert stats.unmatched_transactions == 2
    assert stats.pending_review == 1
    assert stats.auto_accepted == 1

    assert stats.match_rate == pytest.approx(33.33, rel=0.01)
    assert stats.score_distribution is None


async def test_get_reconciliation_stats_dedups_multiple_accepted_matches(db, test_user):
    """AC-reconciliation.stats.1: Two accepted matches on the same atomic txn count as one matched txn.

    ``matched`` counts DISTINCT atomic transactions, so multiple active accepted
    matches on a single transaction must not inflate the count or push
    ``match_rate`` above 100%.
    """
    user_id = test_user.id
    account = Account(
        user_id=user_id,
        name="Test Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    txn = _make_atomic(user_id, txn_date=date(2024, 1, 15), description="Salary", amount=Decimal("5000"))
    db.add(txn)
    await db.flush()

    # Two active accepted matches on the SAME atomic transaction.
    match_a = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(uuid4())],
        match_score=95,
        score_breakdown={"amount": 100.0, "date": 100.0},
        status=ReconciliationStatus.ACCEPTED,
    )
    match_b = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(uuid4())],
        match_score=91,
        score_breakdown={"amount": 100.0, "date": 90.0},
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    db.add_all([match_a, match_b])
    await db.flush()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    assert stats.total_transactions == 1
    # Two accepted matches on one txn => counted once.
    assert stats.matched_transactions == 1
    assert stats.unmatched_transactions == 0
    assert stats.match_rate == pytest.approx(100.0)
    assert stats.match_rate <= 100.0


async def test_get_reconciliation_stats_zero_division(db):
    """Test that zero division is handled when there are no transactions."""
    user_id = uuid4()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    assert stats.total_transactions == 0
    assert stats.matched_transactions == 0
    assert stats.unmatched_transactions == 0
    assert stats.pending_review == 0
    assert stats.auto_accepted == 0
    assert stats.match_rate == 0.0
    assert stats.score_distribution is None


async def test_get_reconciliation_stats_without_distribution(db, test_user):
    """Test that stats work correctly without score distribution."""
    user_id = test_user.id
    account = Account(
        user_id=user_id,
        name="Test Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    txn = _make_atomic(user_id, txn_date=date(2024, 1, 15), description="Test", amount=Decimal("100"))
    db.add(txn)
    await db.flush()

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(uuid4())],
        match_score=85,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    db.add(match)
    await db.flush()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    assert stats.total_transactions == 1
    assert stats.matched_transactions == 1
    assert stats.auto_accepted == 1
    assert stats.score_distribution is None


async def test_get_reconciliation_stats_with_distribution(db, test_user):
    """Test score distribution bucketing with various scores."""
    user_id = test_user.id
    account = Account(
        user_id=user_id,
        name="Test Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()

    scores = [50, 55, 65, 70, 75, 85, 88, 92, 95, 100]
    transactions = [
        _make_atomic(user_id, txn_date=date(2024, 1, 1 + i), description=f"Test {i}", amount=Decimal(str(100 + i)))
        for i in range(len(scores))
    ]
    db.add_all(transactions)
    await db.commit()

    matches = [
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[str(uuid4())],
            match_score=score,
            score_breakdown={"amount": 100.0, "date": 100.0},
            status=ReconciliationStatus.AUTO_ACCEPTED,
        )
        for txn, score in zip(transactions, scores)
    ]
    db.add_all(matches)
    await db.commit()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=True)

    assert stats.score_distribution is not None
    assert stats.score_distribution["0-59"] == 2  # 50, 55
    assert stats.score_distribution["60-79"] == 3  # 65, 70, 75
    assert stats.score_distribution["80-89"] == 2  # 85, 88
    assert stats.score_distribution["90-100"] == 3  # 92, 95, 100
    total_scored = sum(stats.score_distribution.values())
    assert total_scored == 10
