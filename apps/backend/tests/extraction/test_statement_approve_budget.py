"""Cost bound of ``POST /statements/{id}/review/approve`` (#2612).

Staging ``v0.2.25`` took 49.69 s to approve a statement of 80 rows. The local probe of #2612 counted
7 875 SQL statements for that call, about 98 statements for each posted entry. Seven trace records
per entry (four disposition records, three command records) cost 5 to 14 statements each. The
budget below counts the statements the real route issues.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import TransactionDirection
from tests.factories import seed_parsed_statement
from tests.integration.test_statement_corpus_journeys import attach_reviewed_corpus_semantics

pytestmark = pytest.mark.asyncio

ROWS = 80
SMALL_ROWS = 8
# Measured on the fixed code: 116 statements for 80 rows, and the same number for 8 rows (see the PR body).
SQL_BUDGET_AT_80_ROWS = 160
# A statement shape that runs at least once for each entry is a per-entry query. The fixed code has none.
PER_ENTRY_QUERIES_BUDGET_AT_80_ROWS = 0
EXTRA_SQL_PER_EXTRA_ROW_BUDGET = 0.5
# One approve reads the statement, resolves the account, plans the entries and writes them: far more than 30.
MIN_CAPTURED_STATEMENTS = 30


def _rows(count: int, first_day: date) -> list[dict]:
    rows = []
    for index in range(count):
        incoming = index % 7 == 0
        rows.append(
            {
                "description": f"{'Salary' if incoming else 'Merchant'} {index}",
                "amount": Decimal("1000.00") + index if incoming else Decimal("12.34") + index,
                "direction": TransactionDirection.IN if incoming else TransactionDirection.OUT,
                "date": first_day + timedelta(days=index),
            }
        )
    return rows


async def _seed_reviewed_statement(db: AsyncSession, user_id: UUID, *, count: int, first_day: date) -> str:
    seeded = await seed_parsed_statement(
        db,
        user_id,
        institution="DBS",
        original_filename=f"approve_budget_{first_day.isoformat()}.pdf",
        opening_balance=Decimal("1000.00"),
        transactions=_rows(count, first_day),
    )
    seeded.statement.period_start = first_day
    seeded.statement.period_end = first_day + timedelta(days=count - 1)
    await attach_reviewed_corpus_semantics(db, user_id, seeded.transactions)
    await db.commit()
    return str(seeded.id)


async def _approve_and_count(client, db_engine, statement_id: str) -> tuple[dict, list[str]]:
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text

    statements: list[str] = []

    def capture(_conn, _cursor, statement_text, _parameters, _context, _executemany):
        statements.append(re.sub(r"\s+", " ", statement_text).strip())

    event.listen(db_engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await client.post(
            f"/statements/{statement_id}/review/approve", json={"create_account_if_missing": True}
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    # The listener must see the writes of the route. An empty capture would pass any upper bound.
    assert len(statements) > MIN_CAPTURED_STATEMENTS, f"the listener captured {len(statements)} statements"
    return response.json(), statements


def _per_entry_queries(statements: list[str], rows: int) -> int:
    """Count the statements whose shape runs at least once for each row."""
    shapes = Counter(statements)
    return sum(count for count in shapes.values() if count >= rows)


async def test_AC_extraction_statement_approve_2_sql_count_of_80_rows_is_bounded(client, db, db_engine, test_user):
    """AC-extraction.statement-approve.2: approving a statement of 80 rows posts 80 entries with at most
    ``SQL_BUDGET_AT_80_ROWS`` SQL statements, and at most ``PER_ENTRY_QUERIES_BUDGET_AT_80_ROWS`` of them run
    once for each entry. On main at ``bba3aa84`` the call issues 7 875 statements."""
    statement_id = await _seed_reviewed_statement(db, test_user.id, count=ROWS, first_day=date(2026, 1, 1))
    body, statements = await _approve_and_count(client, db_engine, statement_id)

    assert body["journal_entries_created"] == ROWS
    per_entry = _per_entry_queries(statements, ROWS)
    exceeded = []
    if len(statements) > SQL_BUDGET_AT_80_ROWS:
        exceeded.append(f"{len(statements)} SQL statements for {ROWS} rows, budget {SQL_BUDGET_AT_80_ROWS}")
    if per_entry > PER_ENTRY_QUERIES_BUDGET_AT_80_ROWS:
        exceeded.append(
            f"{per_entry} statements repeat once for each entry, budget {PER_ENTRY_QUERIES_BUDGET_AT_80_ROWS}"
        )
    assert not exceeded, "approve exceeded its budget: " + "; ".join(exceeded)


async def test_AC_extraction_statement_approve_3_extra_rows_cost_a_bounded_number_of_statements(
    client, db, db_engine, test_user
):
    """AC-extraction.statement-approve.3: each row above 8 adds at most ``EXTRA_SQL_PER_EXTRA_ROW_BUDGET`` SQL
    statements. The slope is the cost of one more posted entry, free of the fixed cost of a statement."""
    small_id = await _seed_reviewed_statement(db, test_user.id, count=SMALL_ROWS, first_day=date(2026, 1, 1))
    small_body, small_sql = await _approve_and_count(client, db_engine, small_id)
    large_id = await _seed_reviewed_statement(db, test_user.id, count=ROWS, first_day=date(2026, 3, 1))
    large_body, large_sql = await _approve_and_count(client, db_engine, large_id)

    assert small_body["journal_entries_created"] == SMALL_ROWS
    assert large_body["journal_entries_created"] == ROWS
    slope = (len(large_sql) - len(small_sql)) / (ROWS - SMALL_ROWS)
    assert slope <= EXTRA_SQL_PER_EXTRA_ROW_BUDGET, (
        f"{SMALL_ROWS} rows -> {len(small_sql)} statements, {ROWS} rows -> {len(large_sql)} statements, "
        f"slope {slope:.1f} per row, budget {EXTRA_SQL_PER_EXTRA_ROW_BUDGET}"
    )
