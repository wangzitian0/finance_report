"""SQL statement and write-freedom budgets for sampled request endpoints."""

from __future__ import annotations

import contextlib
import re
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

import src.request_context as request_context_mod
from src.extraction import TransactionDirection
from src.identity import User
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.request_context import RequestContext
from src.workflow.extension.events import ensure_workflow_events_synced
from tests.factories import JournalEntryFactory, seed_parsed_statement
from tests.integration.test_statement_corpus_journeys import attach_reviewed_corpus_semantics
from tests.reconciliation.test_stage2_review_router import _seed_approved_statement_with_posted_txn

pytestmark = pytest.mark.asyncio
_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


@contextlib.contextmanager
def _capture_sql(db_engine):
    statements: list[str] = []

    def _listener(_conn, _cursor, statement_text, _parameters, _context, _executemany) -> None:
        statements.append(re.sub(r"\s+", " ", statement_text).strip())

    event.listen(db_engine.sync_engine, "before_cursor_execute", _listener)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _listener)


async def _get_readonly_budget(client: AsyncClient, db_engine, path: str, budget: int | None = None) -> None:
    with _capture_sql(db_engine) as stmts:
        resp = await client.get(path)
    assert resp.status_code == 200, resp.text
    assert [s for s in stmts if s.split(" ", 1)[0].upper() in _WRITE_PREFIXES] == [], stmts
    if budget is not None:
        assert len(stmts) <= budget, stmts


async def test_readonly_endpoint_sql_budgets(client: AsyncClient, db: AsyncSession, db_engine, test_user: User) -> None:
    await JournalEntryFactory.create_balanced_async(db, test_user.id, entry_date=date(2026, 1, 15), memo="Salary")
    await db.commit()
    for path, budget in (("/accounts", 8), ("/reconciliation/transfers/summary", None), ("/reports/balance-sheet", 25), ("/workflow/status", None)):
        await _get_readonly_budget(client, db_engine, path, budget)
    await ensure_workflow_events_synced(db, user_id=test_user.id, base_currency="SGD")
    await db.commit()
    await _get_readonly_budget(client, db_engine, "/workflow/status", 40)


async def test_post_statement_approve_and_batch_accept_sql_budgets(client: AsyncClient, db: AsyncSession, db_engine, test_user: User) -> None:
    first_day = date(2026, 1, 1)
    rows = [{"description": f"{'Salary' if i % 4 == 0 else 'Merchant'} {i}", "amount": Decimal("500.00") if i % 4 == 0 else Decimal("25.00"), "direction": TransactionDirection.IN if i % 4 == 0 else TransactionDirection.OUT, "date": first_day + timedelta(days=i)} for i in range(8)]
    seeded = await seed_parsed_statement(db, test_user.id, institution="DBS", original_filename="request_budget_8.pdf", opening_balance=Decimal("1000.00"), transactions=rows)
    seeded.statement.period_start, seeded.statement.period_end = first_day, first_day + timedelta(days=7)
    await attach_reviewed_corpus_semantics(db, test_user.id, seeded.transactions)
    await db.commit()
    assert (await client.get(f"/statements/{seeded.id}/review")).status_code == 200
    with _capture_sql(db_engine) as stmts:
        resp = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
    assert resp.status_code == 200 and len(stmts) <= 98, (resp.text, len(stmts))

    async def _run_batch(count: int, tag: str) -> int:
        match_ids = []
        for idx in range(count):
            _, _, txn, _ = await _seed_approved_statement_with_posted_txn(db, test_user.id, f"{tag}-{idx}")
            m = ReconciliationMatch(atomic_txn_id=txn.id, match_score=85, status=ReconciliationStatus.PENDING_REVIEW, version=1)
            db.add(m)
            await db.flush()
            match_ids.append(str(m.id))
        await db.commit()
        with _capture_sql(db_engine) as batch_stmts:
            r = await client.post("/reconciliation/matches", json={"action": "accept", "match_ids": match_ids})
        assert r.status_code == 200 and r.json()["approved_count"] == count, r.text
        return len(batch_stmts)

    sql_1, sql_5 = await _run_batch(1, "BudgetBatch1"), await _run_batch(5, "BudgetBatch5")
    assert sql_5 - sql_1 <= 10, f"{sql_1} -> {sql_5}"


@pytest.mark.no_db
async def test_request_context_memoizes_base_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_base_currency(_db, *, user_id) -> str:
        nonlocal calls
        calls += 1
        return "USD"

    monkeypatch.setattr(request_context_mod, "get_effective_base_currency", fake_base_currency)
    ctx = RequestContext(db=AsyncMock(), user_id=uuid4())
    assert await ctx.get_base_currency() == "USD" and await ctx.get_base_currency() == "USD" and calls == 1
