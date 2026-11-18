from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.extraction import BankStatementStatus, Stage1Status, TransactionDirection
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, get_reconciliation_stats
from tests.factories import AccountFactory, seed_parsed_statement
from tests.query_budget import rows_read_by_get, seed_other_tenants, seed_tenant_rows

OTHER_TENANTS = 100
OWN_TRANSACTIONS = 40
OTHER_TRANSACTIONS = 15


async def test_AC_reconciliation_2617_1_stats_do_not_read_matches_of_other_tenants(db, db_engine, client, test_user) -> None:
    await seed_tenant_rows(db, test_user.id, entries=10, transactions=OWN_TRANSACTIONS)
    own_by_table, own_resp = await rows_read_by_get(db_engine, client, "/reconciliation/stats")
    await seed_other_tenants(db, count=OTHER_TENANTS, entries=5, transactions=OTHER_TRANSACTIONS)
    shared_by_table, shared_resp = await rows_read_by_get(db_engine, client, "/reconciliation/stats")
    assert shared_resp.json() == own_resp.json()
    assert (own_resp.json()["total_transactions"], own_resp.json()["matched_transactions"]) == (OWN_TRANSACTIONS, OWN_TRANSACTIONS)
    own_rows, shared_rows = sum(own_by_table.values()), sum(shared_by_table.values())
    assert own_rows > 0 and shared_rows <= 1.25 * own_rows + 100
    assert shared_by_table["reconciliation_matches"] <= own_by_table["reconciliation_matches"] + 40


async def test_AC_reconciliation_2617_2_stats_equal_the_pre_change_values(db, test_user) -> None:
    bank = await AccountFactory.create_async(db, user_id=test_user.id, name="Stats Budget Bank")
    seeded = await seed_parsed_statement(db, test_user.id, transactions=[{"description": f"State {i}", "amount": Decimal("5.00"), "direction": TransactionDirection.OUT, "date": date(2026, 1, 1 + i)} for i in range(12)])
    seeded.statement.account_id, seeded.statement.status, seeded.statement.stage1_status = bank.id, BankStatementStatus.APPROVED, Stage1Status.APPROVED
    await db.flush()
    ids = [t.id for t in seeded.transactions]

    accepted = ReconciliationMatch(id=uuid4(), atomic_txn_id=ids[1], journal_entry_ids=[], status=ReconciliationStatus.ACCEPTED, match_score=85, score_breakdown={})
    db.add(accepted)
    await db.flush()
    specs = [(0, ReconciliationStatus.ACCEPTED, 95, {}), (1, ReconciliationStatus.SUPERSEDED, 40, {"superseded_by_id": accepted.id}), (2, ReconciliationStatus.AUTO_ACCEPTED, 92, {}), (3, ReconciliationStatus.AUTO_ACCEPTED, 88, {}), (4, ReconciliationStatus.PENDING_REVIEW, 72, {}), (5, ReconciliationStatus.PENDING_REVIEW, 65, {}), (6, ReconciliationStatus.REJECTED, 30, {}), (7, ReconciliationStatus.REJECTED, 50, {}), (7, ReconciliationStatus.PENDING_REVIEW, 70, {})]
    db.add_all([ReconciliationMatch(id=uuid4(), atomic_txn_id=ids[idx], journal_entry_ids=[], status=st, match_score=sc, score_breakdown={}, **extra) for idx, st, sc, extra in specs])
    await db.commit()
    await seed_other_tenants(db, count=3, entries=1, transactions=5)
    stats = await get_reconciliation_stats(db, test_user.id, include_distribution=True)
    assert (stats.total_transactions, stats.matched_transactions, stats.pending_review, stats.auto_accepted, stats.unmatched_transactions, stats.match_rate) == (12, 4, 3, 2, 5, 33.33)
    assert stats.score_distribution == {"0-59": 0, "60-79": 3, "80-89": 2, "90-100": 2}
