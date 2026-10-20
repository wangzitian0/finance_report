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

from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
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


async def _make_account(db, user_id, name="Test Account"):
    account = Account(user_id=user_id, name=name, type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    return account


def _make_match(
    txn_id,
    *,
    status=ReconciliationStatus.AUTO_ACCEPTED,
    score=95,
    breakdown=None,
    superseded_by_id=None,
):
    return ReconciliationMatch(
        atomic_txn_id=txn_id,
        journal_entry_ids=[str(uuid4())],
        match_score=score,
        score_breakdown=breakdown or {"amount": 100.0, "date": 100.0},
        status=status,
        superseded_by_id=superseded_by_id,
    )


async def test_get_reconciliation_stats_basic(db, test_user):
    """Test basic reconciliation stats with various match states."""
    user_id = test_user.id
    await _make_account(db, user_id)

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
    match1 = _make_match(txn1.id, score=95)
    match2 = _make_match(
        txn3.id,
        score=70,
        breakdown={"amount": 90.0, "date": 80.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add_all([match1, match2])
    await db.flush()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    assert stats.total_transactions == 3
    # Only accepted/auto-accepted matches count as "matched", and pending_review is not double-counted in unmatched.
    assert stats.matched_transactions == 1
    assert stats.unmatched_transactions == 1
    assert stats.pending_review == 1
    assert stats.auto_accepted == 1

    assert stats.match_rate == pytest.approx(33.33, rel=0.01)
    assert stats.score_distribution is None


async def test_get_reconciliation_stats_dedups_multiple_accepted_matches(db, test_user):
    """AC-reconciliation.stats.1: Historical and active heads count as one matched txn.

    ``matched`` counts DISTINCT atomic transactions and ignores superseded history.
    """
    user_id = test_user.id
    await _make_account(db, user_id)

    txn = _make_atomic(user_id, txn_date=date(2024, 1, 15), description="Salary", amount=Decimal("5000"))
    db.add(txn)
    await db.flush()

    # One historical head and one current head on the same atomic transaction.
    match_b = _make_match(txn.id, score=91, breakdown={"amount": 100.0, "date": 90.0})
    db.add(match_b)
    await db.flush()
    match_a = _make_match(
        txn.id,
        score=95,
        status=ReconciliationStatus.SUPERSEDED,
        superseded_by_id=match_b.id,
    )
    db.add(match_a)
    await db.flush()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=False)

    assert stats.total_transactions == 1
    # Superseded history plus one active head => counted once.
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
    await _make_account(db, user_id)

    txn = _make_atomic(user_id, txn_date=date(2024, 1, 15), description="Test", amount=Decimal("100"))
    db.add(txn)
    await db.flush()

    match = _make_match(txn.id, score=85, breakdown={"amount": 100.0})
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
    await _make_account(db, user_id)

    scores = [50, 55, 65, 70, 75, 85, 88, 92, 95, 100]
    transactions = [
        _make_atomic(user_id, txn_date=date(2024, 1, 1 + i), description=f"Test {i}", amount=Decimal(str(100 + i)))
        for i in range(len(scores))
    ]
    db.add_all(transactions)
    await db.commit()

    matches = [_make_match(txn.id, score=score) for txn, score in zip(transactions, scores)]
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


def test_stats_reexports_ssot_confidence_thresholds():
    """Verify stats module re-exports SSOT reconciliation confidence thresholds."""
    from src.reconciliation.data import RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE

    assert RECONCILIATION_AUTO_ACCEPT_SCORE == 85
    assert RECONCILIATION_REVIEW_SCORE == 60


async def _seed_reviewed_statement_row(db, user_id, file_hash):
    """Seed one approved statement with one salary row and a reviewed disposition rule; do not post it."""
    from src.extraction import BankStatementStatus
    from tests.api._statement_router_fixtures import (
        add_reviewed_disposition_rule,
        add_txn,
        build_statement,
        create_statement_account,
    )

    bank_account = await create_statement_account(db, user_id, "DBS Stats Posted")
    statement = build_statement(user_id, file_hash, 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db, user_id=user_id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
    )
    await db.commit()
    return statement, txn


async def test_AC_reconciliation_2465_1_statement_posted_rows_count_as_matched(db, test_user):
    """AC-reconciliation.2465.1: a row that the system posted from its own statement is reconciled by construction.

    The stats count it as matched and the unmatched list does not show it, so a
    clean upload reads 100% matched instead of asking the user to review rows
    that are already posted.
    """

    from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
    from src.routers.reconciliation import _unmatched_atomic_txn_query
    from tests.statement_ingestion import posting_dependencies

    statement, _txn = await _seed_reviewed_statement_row(db, test_user.id, "hash_stats_posted_2465")

    before = await get_reconciliation_stats(db, test_user.id)
    assert before.total_transactions == 1
    assert before.matched_transactions == 0
    assert before.unmatched_transactions == 1

    posted = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )
    assert posted == 1

    after = await get_reconciliation_stats(db, test_user.id)
    assert after.total_transactions == 1
    assert after.matched_transactions == 1
    assert after.unmatched_transactions == 0
    assert after.match_rate == 100.0
    unmatched_rows = (await db.execute(_unmatched_atomic_txn_query(test_user.id))).scalars().all()
    assert unmatched_rows == []


async def test_AC_reconciliation_2561_1_run_after_statement_posting_creates_no_self_match(db, test_user):
    """AC-reconciliation.2561.1: a reconciliation run skips a row that its own statement already posted.

    The run creates no match for that row, and the stats still count it as matched.
    Core journey U13 runs a reconciliation after approval and reads these two facts (#2561, #2554).
    """
    from sqlalchemy import func, select

    from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
    from src.reconciliation import execute_matching
    from tests.statement_ingestion import posting_dependencies

    statement, txn = await _seed_reviewed_statement_row(db, test_user.id, "hash_stats_posted_2561")
    posted = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )
    assert posted == 1

    matches = await execute_matching(db, user_id=test_user.id, currency="SGD")
    assert matches == []
    match_count = await db.scalar(
        select(func.count(ReconciliationMatch.id)).where(ReconciliationMatch.atomic_txn_id == txn.id)
    )
    assert match_count == 0

    stats = await get_reconciliation_stats(db, test_user.id)
    assert stats.total_transactions == 1
    assert stats.matched_transactions == 1
    assert stats.unmatched_transactions == 0
    assert stats.auto_accepted == 0


async def test_AC_reconciliation_2548_3_stats_unmatched_aligns_with_unmatched_query(db, test_user):
    """AC-reconciliation.2548.3: stats.unmatched_transactions equals the /reconciliation/unmatched total (#2548)."""
    from src.extraction import BankStatementStatus, DocumentType, UploadedDocument
    from src.extraction.orm.statement_summary import StatementSummary
    from src.routers.reconciliation import _unmatched_atomic_txn_query

    user_id = test_user.id
    await _make_account(db, user_id)

    retired_doc = UploadedDocument(
        id=uuid4(),
        user_id=user_id,
        file_path="statements/retired.pdf",
        file_hash=f"retired_{uuid4().hex}",
        original_filename="retired.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(retired_doc)
    await db.flush()
    retired_stmt = StatementSummary(
        id=uuid4(),
        user_id=user_id,
        uploaded_document_id=retired_doc.id,
        file_hash=retired_doc.file_hash,
        institution="Bank",
        currency="SGD",
        status=BankStatementStatus.RETIRED,
    )
    db.add(retired_stmt)
    await db.flush()

    retired_txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2026, 2, 1),
        description="Retired statement row",
        amount=Decimal("50.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(retired_doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )
    txn_auto = _make_atomic(user_id, txn_date=date(2026, 2, 2), description="Salary", amount=Decimal("3000.00"))
    txn_pending = _make_atomic(user_id, txn_date=date(2026, 2, 3), description="Rent", amount=Decimal("1200.00"))
    txn_unmatched = _make_atomic(user_id, txn_date=date(2026, 2, 4), description="Coffee", amount=Decimal("6.50"))
    db.add_all([retired_txn, txn_auto, txn_pending, txn_unmatched])
    await db.flush()

    active_auto = _make_match(txn_auto.id, score=92, status=ReconciliationStatus.AUTO_ACCEPTED)
    db.add(active_auto)
    await db.flush()
    superseded_old = _make_match(
        txn_auto.id,
        score=70,
        status=ReconciliationStatus.PENDING_REVIEW,
        superseded_by_id=active_auto.id,
    )
    pending_match = _make_match(txn_pending.id, score=72, status=ReconciliationStatus.PENDING_REVIEW)
    db.add_all([superseded_old, pending_match])
    await db.commit()

    stats = await get_reconciliation_stats(db, user_id, include_distribution=True)
    unmatched_rows = (await db.execute(_unmatched_atomic_txn_query(user_id))).scalars().all()

    assert stats.total_transactions == 3
    assert stats.matched_transactions == 1
    assert stats.pending_review == 1
    assert stats.unmatched_transactions == 1
    assert stats.unmatched_transactions == len(unmatched_rows)
    assert [row.id for row in unmatched_rows] == [txn_unmatched.id]
    assert stats.score_distribution is not None
    assert sum(stats.score_distribution.values()) == 2
