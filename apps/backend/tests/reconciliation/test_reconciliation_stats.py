from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.extraction import BankStatementStatus, TransactionDirection
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.ledger import AccountType
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, execute_matching, get_reconciliation_stats
from src.reconciliation.data import RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reporting.extension.data_quality_service import compute_personal_data_quality
from src.request_context import RequestContext
from src.routers.reconciliation import _unmatched_atomic_txn_query, list_unmatched
from tests.api._statement_router_fixtures import add_reviewed_disposition_rule, add_txn, build_statement, create_statement_account
from tests.factories import AccountFactory, AtomicTransactionFactory, ReconciliationMatchFactory, UserFactory, seed_parsed_statement
from tests.statement_ingestion import posting_dependencies


async def test_get_reconciliation_stats_dedup_distribution_and_unmatched_alignment(db, test_user) -> None:
    assert (RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE) == (85, 60)
    empty = await get_reconciliation_stats(db, uuid4(), include_distribution=False)
    assert (empty.total_transactions, empty.matched_transactions, empty.unmatched_transactions, empty.pending_review, empty.auto_accepted, empty.match_rate, empty.score_distribution) == (0, 0, 0, 0, 0, 0.0, None)

    uid = test_user.id
    await AccountFactory.create_async(db, user_id=uid)
    txns = [
        await AtomicTransactionFactory.create_async(db, user_id=uid, txn_date=date(2024, 1, 15 + i), description=desc, amount=Decimal(amt), direction=direction)
        for i, (desc, amt, direction) in enumerate([("Salary", "5000", TransactionDirection.IN), ("Groceries", "100", TransactionDirection.OUT), ("Rent", "2000", TransactionDirection.OUT)])
    ]
    m1 = await ReconciliationMatchFactory.create_async(db, atomic_txn_id=txns[0].id, match_score=95, status=ReconciliationStatus.AUTO_ACCEPTED)
    await ReconciliationMatchFactory.create_async(db, atomic_txn_id=txns[2].id, match_score=70, status=ReconciliationStatus.PENDING_REVIEW)
    stats = await get_reconciliation_stats(db, uid, include_distribution=False)
    assert (stats.total_transactions, stats.matched_transactions, stats.unmatched_transactions, stats.pending_review, stats.auto_accepted, stats.score_distribution) == (3, 1, 1, 1, 1, None)
    assert stats.match_rate == pytest.approx(33.33, rel=0.01)

    await ReconciliationMatchFactory.create_async(db, atomic_txn_id=txns[0].id, match_score=91, status=ReconciliationStatus.SUPERSEDED, superseded_by_id=m1.id)
    assert (await get_reconciliation_stats(db, uid, include_distribution=False)).matched_transactions == 1

    scores = [50, 55, 65, 70, 75, 85, 88, 92, 95, 100]
    uid2 = (await UserFactory.create_async(db)).id
    await AccountFactory.create_async(db, user_id=uid2)
    retired = await seed_parsed_statement(db, uid2, original_filename="retired.pdf", transactions=[{"description": "Retired", "amount": Decimal("50.00"), "direction": TransactionDirection.OUT, "date": date(2026, 2, 1)}])
    retired.statement.status = BankStatementStatus.RETIRED
    for i, s in enumerate(scores):
        t = await AtomicTransactionFactory.create_async(db, user_id=uid2, txn_date=date(2024, 2, 1 + i), description=f"D{i}", amount=Decimal(str(100 + i)))
        await ReconciliationMatchFactory.create_async(db, atomic_txn_id=t.id, match_score=s, status=ReconciliationStatus.AUTO_ACCEPTED)
    t_pend = await AtomicTransactionFactory.create_async(db, user_id=uid2, txn_date=date(2026, 2, 3), description="Rent", amount=Decimal("1200.00"))
    t_u = await AtomicTransactionFactory.create_async(db, user_id=uid2, txn_date=date(2026, 2, 4), description="Coffee", amount=Decimal("6.50"))
    await ReconciliationMatchFactory.create_async(db, atomic_txn_id=t_pend.id, match_score=72, status=ReconciliationStatus.PENDING_REVIEW)
    await db.commit()
    dist_stats = await get_reconciliation_stats(db, uid2, include_distribution=True)
    assert dist_stats.score_distribution == {"0-59": 2, "60-79": 4, "80-89": 2, "90-100": 3}
    assert (dist_stats.total_transactions, dist_stats.matched_transactions, dist_stats.pending_review, dist_stats.unmatched_transactions) == (12, 10, 1, 1)
    assert [r.id for r in (await db.execute(_unmatched_atomic_txn_query(uid2))).scalars().all()] == [t_u.id]


async def test_AC_reconciliation_2465_and_2826_posted_and_stage2_scope(db, test_user) -> None:
    uid = test_user.id
    bank = await create_statement_account(db, uid, "DBS Stats Posted")
    stmt = build_statement(uid, "hash_stats_posted_2465", 90)
    stmt.status, stmt.account_id, stmt.closing_balance = BankStatementStatus.APPROVED, bank.id, Decimal("120.00")
    db.add(stmt)
    await db.flush()
    txn = await add_txn(db, stmt, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN")
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(db, user_id=uid, keyword="salary", account_type=AccountType.INCOME, category="SALARY")
    await db.commit()

    before = await get_reconciliation_stats(db, uid)
    assert (before.total_transactions, before.matched_transactions, before.unmatched_transactions) == (1, 0, 1)
    assert await try_auto_approve_high_confidence_statement(db, stmt.id, uid, dependencies=posting_dependencies()) == 1
    after = await get_reconciliation_stats(db, uid)
    assert (after.total_transactions, after.matched_transactions, after.unmatched_transactions, after.match_rate, after.auto_accepted) == (1, 1, 0, 100.0, 0)
    assert (await db.execute(_unmatched_atomic_txn_query(uid))).scalars().all() == []
    repo = SqlReconciliationRepository(db)
    assert {c.source_id for c in await repo.list_journal_candidates(user_id=uid, start_date=txn.txn_date, end_date=txn.txn_date)} == {txn.id}
    assert txn.id not in {r.id for r in await repo.list_pending_transactions(uid)}
    assert await execute_matching(db, user_id=uid, currency="SGD") == []
    assert await db.scalar(select(func.count(ReconciliationMatch.id)).where(ReconciliationMatch.atomic_txn_id == txn.id)) == 0

    parsed = await seed_parsed_statement(db, uid, original_filename="parsed_2826.csv", transactions=[{"description": "Pending Stage-1", "amount": Decimal("42.00"), "direction": TransactionDirection.OUT, "date": date(2026, 3, 10)}])
    approved = await seed_parsed_statement(db, uid, original_filename="approved_2826.csv", transactions=[{"description": "Approved Stage-2", "amount": Decimal("88.00"), "direction": TransactionDirection.OUT, "date": date(2026, 2, 10)}])
    approved.statement.account_id, approved.statement.status = bank.id, BankStatementStatus.APPROVED
    await db.commit()
    parsed_txn, approved_txn = parsed.transactions[0], approved.transactions[0]
    s2 = await get_reconciliation_stats(db, uid)
    assert (s2.total_transactions, s2.unmatched_transactions) == (2, 1)
    unscoped = await list_unmatched(statement_id=None, limit=100, offset=0, ctx=RequestContext(db, uid))
    scoped = await list_unmatched(statement_id=parsed.statement.id, limit=100, offset=0, ctx=RequestContext(db, uid))
    assert [i.id for i in unscoped.items] == [approved_txn.id] and unscoped.total == 1
    assert [i.id for i in scoped.items] == [parsed_txn.id] and scoped.total == 1
    assert {i.id for i in await repo.list_pending_transactions(uid)} == {parsed_txn.id, approved_txn.id}
    assert (await compute_personal_data_quality(db, uid, as_of_date=date(2026, 3, 31), currency="SGD")).reconciliation_purity_invariant.delta == Decimal(1)
