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
ROWS, SMALL_ROWS = 80, 8


def _rows(count: int, first_day: date) -> list[dict]:
    return [
        {
            "description": f"{'Salary' if i % 7 == 0 else 'Merchant'} {i}",
            "amount": Decimal("1000.00") + i if i % 7 == 0 else Decimal("12.34") + i,
            "direction": TransactionDirection.IN if i % 7 == 0 else TransactionDirection.OUT,
            "date": first_day + timedelta(days=i),
        }
        for i in range(count)
    ]


async def _seed_reviewed_statement(db: AsyncSession, user_id: UUID, *, count: int, first_day: date) -> str:
    seeded = await seed_parsed_statement(db, user_id, institution="DBS", original_filename=f"approve_budget_{first_day.isoformat()}.pdf", opening_balance=Decimal("1000.00"), transactions=_rows(count, first_day))
    seeded.statement.period_start, seeded.statement.period_end = first_day, first_day + timedelta(days=count - 1)
    await attach_reviewed_corpus_semantics(db, user_id, seeded.transactions)
    await db.commit()
    return str(seeded.id)


async def _approve_and_count(client, db_engine, statement_id: str) -> tuple[dict, list[str]]:
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text
    statements: list[str] = []

    def capture(_conn, _cursor, statement_text, *_args):
        statements.append(re.sub(r"\s+", " ", statement_text).strip())

    event.listen(db_engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await client.post(f"/statements/{statement_id}/approvals", json={"create_account_if_missing": True})
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200 and len(statements) > 30
    return response.json(), statements


async def test_AC_extraction_statement_approve_2_3_sql_budget_and_scaling(client, db, db_engine, test_user):
    small_id = await _seed_reviewed_statement(db, test_user.id, count=SMALL_ROWS, first_day=date(2026, 1, 1))
    small_body, small_sql = await _approve_and_count(client, db_engine, small_id)
    large_id = await _seed_reviewed_statement(db, test_user.id, count=ROWS, first_day=date(2026, 3, 1))
    large_body, large_sql = await _approve_and_count(client, db_engine, large_id)
    per_entry = sum(c for c in Counter(large_sql).values() if c >= ROWS)
    slope = (len(large_sql) - len(small_sql)) / (ROWS - SMALL_ROWS)
    assert (small_body["journal_entries_created"], large_body["journal_entries_created"]) == (SMALL_ROWS, ROWS)
    assert len(large_sql) <= 100 and per_entry == 0 and slope <= 0.5
