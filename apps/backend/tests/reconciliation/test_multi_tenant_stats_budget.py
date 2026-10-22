"""Reconciliation statistics do not read the matches of other users (#2617).

``reconciliation_matches`` has no ``user_id``. Before #2617, ``get_reconciliation_stats`` joined the
matches to the transactions of the user, and it tested "accepted match" with ``atomic_txn_id IN
(SELECT ... FROM reconciliation_matches WHERE status ...)``. That set holds the matches of every
user. Without statistics, the planner scanned all matches in each of the statements of
``GET /reconciliation/stats``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.extraction import TransactionDirection
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, get_reconciliation_stats
from tests.factories import seed_parsed_statement
from tests.query_budget import rows_read_by_get, seed_other_tenants, seed_tenant_rows

OTHER_TENANTS = 100
OWN_TRANSACTIONS = 40
OTHER_TRANSACTIONS = 15
GROWTH_FACTOR = 1.25
GROWTH_ALLOWANCE_ROWS = 100
# The match rate that the version before #2617 returned for the data of the second test.
PRE_CHANGE_MATCH_RATE = 33.33


@pytest.mark.asyncio
async def test_AC_reconciliation_2617_1_stats_do_not_read_matches_of_other_tenants(
    db, db_engine, client, test_user
) -> None:
    """AC-reconciliation.2617.1: with 100 more users and their accepted matches in the database,
    ``GET /reconciliation/stats`` reads at most 1.25 times the rows (plus 100) that it reads
    when the database holds one user, and it reads no match row of another user.
    The counts of the user do not change."""
    user_id = test_user.id
    await seed_tenant_rows(db, user_id, entries=10, transactions=OWN_TRANSACTIONS)
    own_rows_by_table, own_response = await rows_read_by_get(db_engine, client, "/reconciliation/stats")

    await seed_other_tenants(db, count=OTHER_TENANTS, entries=5, transactions=OTHER_TRANSACTIONS)
    shared_rows_by_table, shared_response = await rows_read_by_get(db_engine, client, "/reconciliation/stats")

    assert shared_response.json() == own_response.json()
    assert own_response.json()["total_transactions"] == OWN_TRANSACTIONS
    assert own_response.json()["matched_transactions"] == OWN_TRANSACTIONS
    own_rows = sum(own_rows_by_table.values())
    shared_rows = sum(shared_rows_by_table.values())
    assert own_rows > 0, "the stats read no row: the budget would pass on an empty read"
    assert shared_rows <= GROWTH_FACTOR * own_rows + GROWTH_ALLOWANCE_ROWS, (
        f"GET /reconciliation/stats reads {shared_rows} rows with {OTHER_TENANTS} other users "
        f"and {own_rows} rows alone. By table, alone: {dict(own_rows_by_table)}; shared: {dict(shared_rows_by_table)}"
    )
    # The 100 other users add 1500 matches. The statements may not read one of them.
    assert shared_rows_by_table["reconciliation_matches"] <= own_rows_by_table["reconciliation_matches"] + 40, (
        shared_rows_by_table
    )


async def _seed_match_states(db, user_id) -> None:
    """Add twelve transactions of one statement. They hold every match state that the statistics count."""
    seeded = await seed_parsed_statement(
        db,
        user_id,
        transactions=[
            {
                "description": f"State {index}",
                "amount": Decimal("5.00"),
                "direction": TransactionDirection.OUT,
                "date": date(2026, 1, 1 + index),
            }
            for index in range(12)
        ],
    )
    ids = [transaction.id for transaction in seeded.transactions]

    def add_match(index: int, status: ReconciliationStatus, score: int, **extra) -> ReconciliationMatch:
        row = ReconciliationMatch(
            id=uuid4(),
            atomic_txn_id=ids[index],
            journal_entry_ids=[],
            status=status,
            match_score=score,
            score_breakdown={},
            **extra,
        )
        db.add(row)
        return row

    accepted = add_match(1, ReconciliationStatus.ACCEPTED, 85)
    await db.flush()
    add_match(0, ReconciliationStatus.ACCEPTED, 95)
    add_match(1, ReconciliationStatus.SUPERSEDED, 40, superseded_by_id=accepted.id)
    add_match(2, ReconciliationStatus.AUTO_ACCEPTED, 92)
    add_match(3, ReconciliationStatus.AUTO_ACCEPTED, 88)
    add_match(4, ReconciliationStatus.PENDING_REVIEW, 72)
    add_match(5, ReconciliationStatus.PENDING_REVIEW, 65)
    add_match(6, ReconciliationStatus.REJECTED, 30)
    add_match(7, ReconciliationStatus.REJECTED, 50)
    add_match(7, ReconciliationStatus.PENDING_REVIEW, 70)
    await db.commit()


@pytest.mark.asyncio
async def test_AC_reconciliation_2617_2_stats_equal_the_pre_change_values(db, test_user) -> None:
    """AC-reconciliation.2617.2: ``get_reconciliation_stats`` returns the values of the version before
    #2617 for twelve transactions in every match state, with the accepted matches of other users present.
    The expected values come from a run of that version."""
    await _seed_match_states(db, test_user.id)
    await seed_other_tenants(db, count=3, entries=1, transactions=5)

    stats = await get_reconciliation_stats(db, test_user.id, include_distribution=True)

    assert (stats.total_transactions, stats.matched_transactions, stats.pending_review, stats.auto_accepted) == (
        12,
        4,
        3,
        2,
    )
    assert stats.unmatched_transactions == 5
    assert stats.match_rate == PRE_CHANGE_MATCH_RATE
    assert stats.score_distribution == {"0-59": 0, "60-79": 3, "80-89": 2, "90-100": 2}
