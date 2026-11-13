"""POST /statements/batch-approve-matches: statement count grows by a bounded amount per extra match."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import event

from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from tests.api.test_review_router import _seed_approved_statement_with_posted_txn

pytestmark = pytest.mark.asyncio

MAX_EXTRA_STATEMENTS_PER_MATCH = 3


async def _approve_batch_and_count(client, db, db_engine, user_id, count: int) -> tuple[dict, int]:
    ids = []
    for index in range(count):
        _, _, txn, _ = await _seed_approved_statement_with_posted_txn(db, user_id, f"DBS Batch {count}-{index}")
        match = ReconciliationMatch(
            atomic_txn_id=txn.id, match_score=75, status=ReconciliationStatus.PENDING_REVIEW, version=1
        )
        db.add(match)
        await db.flush()
        ids.append(str(match.id))
    await db.commit()

    statements: list[str] = []

    def capture(_conn, _cursor, statement_text, _parameters, _context, _executemany):
        statements.append(re.sub(r"\s+", " ", statement_text).strip())

    event.listen(db_engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await client.post("/statements/batch-approve-matches", json={"match_ids": ids})
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    return response.json(), len(statements)


async def test_batch_approve_over_http_costs_a_bounded_number_of_statements_per_match(client, db, db_engine, test_user):
    "AC-reconciliation.stage2-batch.3"
    small_body, small_sql = await _approve_batch_and_count(client, db, db_engine, test_user.id, 2)
    large_body, large_sql = await _approve_batch_and_count(client, db, db_engine, test_user.id, 6)

    assert small_body["approved_count"] == 2
    assert large_body["approved_count"] == 6
    assert set(large_body) == {"approved_count", "journal_entries_reconciled"}
    slope = (large_sql - small_sql) / 4
    assert slope <= MAX_EXTRA_STATEMENTS_PER_MATCH, f"{small_sql} -> {large_sql} statements, slope {slope:.1f}"
