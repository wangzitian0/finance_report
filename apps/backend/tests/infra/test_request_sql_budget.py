"""SQL statement and write-freedom budgets for the five sampled request endpoints."""

from __future__ import annotations

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
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.request_context import RequestContext
from src.workflow.extension.events import ensure_workflow_events_synced
from tests.api.test_review_router import _seed_approved_statement_with_posted_txn
from tests.factories import seed_parsed_statement
from tests.integration.test_statement_corpus_journeys import attach_reviewed_corpus_semantics

pytestmark = pytest.mark.asyncio

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")
_BUDGET_GET_ACCOUNTS = 8
_BUDGET_GET_BALANCE_SHEET = 25
_BUDGET_GET_WORKFLOW_STATUS_STEADY = 40
_BUDGET_POST_APPROVE_8_ROWS = 98
_BUDGET_BATCH_APPROVE_EXTRA_4_SQL = 10


def _capture_sql(db_engine):
    statements: list[str] = []

    def _listener(_conn, _cursor, statement_text, _parameters, _context, _executemany) -> None:
        statements.append(re.sub(r"\s+", " ", statement_text).strip())

    event.listen(db_engine.sync_engine, "before_cursor_execute", _listener)
    return statements, lambda: event.remove(db_engine.sync_engine, "before_cursor_execute", _listener)


def _writes(statements: list[str]) -> list[str]:
    return [stmt for stmt in statements if stmt.split(" ", 1)[0].upper() in _WRITE_PREFIXES]


async def test_get_accounts_and_processing_summary_are_read_only_and_bounded(client: AsyncClient, db_engine) -> None:
    """AC-platform.request-sql-budget.1: verify /accounts read endpoints are write-free and bounded."""
    statements, detach = _capture_sql(db_engine)
    try:
        accounts_resp = await client.get("/accounts")
    finally:
        detach()
    assert accounts_resp.status_code == 200, accounts_resp.text
    assert _writes(statements) == []
    assert len(statements) <= _BUDGET_GET_ACCOUNTS, statements

    proc_statements, proc_detach = _capture_sql(db_engine)
    try:
        proc_resp = await client.get("/accounts/processing/summary")
    finally:
        proc_detach()
    assert proc_resp.status_code == 200, proc_resp.text
    assert _writes(proc_statements) == []


async def test_get_balance_sheet_is_read_only_and_bounded(
    client: AsyncClient, db: AsyncSession, db_engine, test_user: User
) -> None:
    """AC-platform.request-sql-budget.2: verify /reports/balance-sheet is write-free and bounded."""
    bank = Account(user_id=test_user.id, name="Checking", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, salary])
    await db.flush()
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 1, 15),
        memo="Salary deposit",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    statements, detach = _capture_sql(db_engine)
    try:
        resp = await client.get("/reports/balance-sheet")
    finally:
        detach()
    assert resp.status_code == 200, resp.text
    assert _writes(statements) == []
    assert len(statements) <= _BUDGET_GET_BALANCE_SHEET, statements


async def test_get_workflow_status_steady_read_is_read_only_and_bounded(
    client: AsyncClient, db: AsyncSession, db_engine, test_user: User
) -> None:
    """AC-platform.request-sql-budget.3: verify /workflow/status cold and steady reads are write-free and bounded."""
    cold_statements, cold_detach = _capture_sql(db_engine)
    try:
        cold = await client.get("/workflow/status")
    finally:
        cold_detach()
    assert cold.status_code == 200, cold.text
    assert _writes(cold_statements) == []

    await ensure_workflow_events_synced(db, user_id=test_user.id)
    await db.commit()

    statements, detach = _capture_sql(db_engine)
    try:
        resp = await client.get("/workflow/status")
    finally:
        detach()
    assert resp.status_code == 200, resp.text
    assert _writes(statements) == []
    assert len(statements) <= _BUDGET_GET_WORKFLOW_STATUS_STEADY, statements


async def test_post_statement_approve_sql_count_is_bounded(
    client: AsyncClient, db: AsyncSession, db_engine, test_user: User
) -> None:
    """AC-platform.request-sql-budget.4: verify statement approve SQL count stays within budget."""
    first_day = date(2026, 1, 1)
    rows = [
        {
            "description": f"{'Salary' if i % 4 == 0 else 'Merchant'} {i}",
            "amount": Decimal("500.00") if i % 4 == 0 else Decimal("25.00"),
            "direction": TransactionDirection.IN if i % 4 == 0 else TransactionDirection.OUT,
            "date": first_day + timedelta(days=i),
        }
        for i in range(8)
    ]
    seeded = await seed_parsed_statement(
        db,
        test_user.id,
        institution="DBS",
        original_filename="request_budget_8.pdf",
        opening_balance=Decimal("1000.00"),
        transactions=rows,
    )
    seeded.statement.period_start = first_day
    seeded.statement.period_end = first_day + timedelta(days=7)
    await attach_reviewed_corpus_semantics(db, test_user.id, seeded.transactions)
    await db.commit()

    review = await client.get(f"/statements/{seeded.id}/review")
    assert review.status_code == 200, review.text

    statements, detach = _capture_sql(db_engine)
    try:
        resp = await client.post(f"/statements/{seeded.id}/review/approve", json={"create_account_if_missing": True})
    finally:
        detach()
    assert resp.status_code == 200, resp.text
    assert len(statements) <= _BUDGET_POST_APPROVE_8_ROWS, f"{len(statements)} statements: {statements}"


async def test_post_reconciliation_batch_accept_sql_count_is_bounded(
    client: AsyncClient, db: AsyncSession, db_engine, test_user: User
) -> None:
    """AC-platform.request-sql-budget.5: verify batch match accept extra SQL stays bounded."""

    async def _run_batch(count: int, tag: str) -> int:
        match_ids = []
        for idx in range(count):
            _, _, txn, _ = await _seed_approved_statement_with_posted_txn(db, test_user.id, f"{tag}-{idx}")
            match = ReconciliationMatch(
                atomic_txn_id=txn.id,
                match_score=85,
                status=ReconciliationStatus.PENDING_REVIEW,
                version=1,
            )
            db.add(match)
            await db.flush()
            match_ids.append(str(match.id))
        await db.commit()

        statements, detach = _capture_sql(db_engine)
        try:
            resp = await client.post("/reconciliation/matches", json={"action": "accept", "match_ids": match_ids})
        finally:
            detach()
        assert resp.status_code == 200, resp.text
        assert resp.json()["approved_count"] == count
        return len(statements)

    sql_1 = await _run_batch(1, "BudgetBatch1")
    sql_5 = await _run_batch(5, "BudgetBatch5")
    assert sql_5 - sql_1 <= _BUDGET_BATCH_APPROVE_EXTRA_4_SQL, f"{sql_1} -> {sql_5}"


@pytest.mark.no_db
async def test_request_context_memoizes_base_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-platform.request-sql-budget.6: verify RequestContext queries base currency at most once."""
    calls = 0

    async def fake_base_currency(_db, *, user_id) -> str:
        nonlocal calls
        calls += 1
        return "USD"

    monkeypatch.setattr(request_context_mod, "get_effective_base_currency", fake_base_currency)
    ctx = RequestContext(db=AsyncMock(), user_id=uuid4())
    assert await ctx.get_base_currency() == "USD"
    assert await ctx.get_base_currency() == "USD"
    assert calls == 1
