"""Year-scale reporting validation (#951, EPIC-005 AC5.20).

A single user's full year of activity is low-thousands of journal lines. This
gates (in the default CI lane) that the balance sheet, income statement, and
cash flow still produce correct, tied-out numbers at that volume — guarding the
income-statement Python-side aggregation against a silent O(n^2) regression — and
keeps generation under a generous wall-clock backstop.
"""

import time
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
)
from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement
from tests.factories import seed_year_of_journal_entries

ENTRY_COUNT = 1000
AMOUNT = Decimal("100.00")
LATENCY_BUDGET_SECONDS = 30.0  # generous regression backstop, not a benchmark


async def test_AC5_20_year_scale_reporting_ties_out_within_budget(db: AsyncSession, test_user) -> None:
    """AC-reporting.year-scale.1: AC5.20.1: at a full year's transaction volume the three core statements
    tie out and generate within a generous wall-clock budget."""
    user_id = test_user.id
    bank = Account(user_id=user_id, name="Bank", code="1001", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", code="4001", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, salary])
    await db.flush()

    now = datetime.now(UTC)
    start = date(2026, 1, 1)
    entry_rows = []
    line_rows = []
    for i in range(ENTRY_COUNT):
        entry_id = uuid4()
        entry_rows.append(
            {
                "id": entry_id,
                "user_id": user_id,
                "entry_date": start + timedelta(days=i % 365),
                "memo": f"txn {i}",
                "source_type": JournalEntrySourceType.MANUAL,
                "source_id": None,
                "decision_anchor_id": None,
                "decision_authority_state": JournalEntryAuthorityState.LEGACY_UNPROVEN,
                "status": JournalEntryStatus.POSTED,
                "void_reason": None,
                "void_reversal_entry_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        line_rows.append(
            {
                "id": uuid4(),
                "journal_entry_id": entry_id,
                "account_id": bank.id,
                "direction": Direction.DEBIT,
                "amount": AMOUNT,
                "currency": "SGD",
                "fx_rate": None,
                "event_type": None,
                "tags": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        line_rows.append(
            {
                "id": uuid4(),
                "journal_entry_id": entry_id,
                "account_id": salary.id,
                "direction": Direction.CREDIT,
                "amount": AMOUNT,
                "currency": "SGD",
                "fx_rate": None,
                "event_type": None,
                "tags": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    await db.execute(insert(JournalEntry), entry_rows)
    await db.execute(insert(JournalLine), line_rows)
    await db.commit()

    period_start = date(2026, 1, 1)
    period_end = date(2026, 12, 31)
    started = time.perf_counter()
    balance_sheet = await generate_balance_sheet(db, user_id, as_of_date=period_end, currency="SGD")
    income_statement = await generate_income_statement(
        db, user_id, start_date=period_start, end_date=period_end, currency="SGD"
    )
    cash_flow = await generate_cash_flow(db, user_id, start_date=period_start, end_date=period_end, currency="SGD")
    elapsed = time.perf_counter() - started

    expected_total = AMOUNT * ENTRY_COUNT  # 100000.00
    assert income_statement["total_income"] == expected_total
    assert income_statement["net_income"] == expected_total
    assert balance_sheet["total_assets"] == expected_total
    assert balance_sheet["is_balanced"] is True
    assert cash_flow["summary"]["ending_cash"] == expected_total
    assert elapsed < LATENCY_BUDGET_SECONDS, (
        f"year-scale reporting took {elapsed:.2f}s (budget {LATENCY_BUDGET_SECONDS}s)"
    )


SERIES_SQL_BUDGET = 30
SERIES_LATENCY_BUDGET_SECONDS = 0.5


def _months_before(value: date, months: int) -> date:
    """Return the same day ``months`` months earlier, clamped to the month end (the Home chart range)."""
    year, month_index = divmod(value.year * 12 + value.month - 1 - months, 12)
    return date(year, month_index + 1, min(value.day, monthrange(year, month_index + 1)[1]))


async def test_AC_reporting_net_worth_timeseries_4_six_month_daily_series_within_budget(
    client, db: AsyncSession, db_engine, test_user
) -> None:
    """AC-reporting.net-worth-timeseries.4: at a year of activity (1000 entries), the Home
    default series (6 months, daily) makes fewer than 30 SQL statements and answers in
    less than 500 ms. Before #2583 it ran one balance sheet per point (about 2000 statements)."""
    today = date.today()
    await seed_year_of_journal_entries(db, test_user.id, first_day=today - timedelta(days=364), entry_count=ENTRY_COUNT)

    statements = {"count": 0}

    @event.listens_for(db_engine.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        statements["count"] += 1

    params = {
        "from": _months_before(today, 6).isoformat(),
        "to": today.isoformat(),
        "granularity": "daily",
        "currency": "SGD",
    }
    try:
        warm_up = await client.get("/reports/net-worth/timeseries", params=params)
        assert warm_up.status_code == 200, warm_up.text
        statements["count"] = 0
        started = time.perf_counter()
        response = await client.get("/reports/net-worth/timeseries", params=params)
        elapsed = time.perf_counter() - started
        statement_count = statements["count"]
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _count)

    assert response.status_code == 200, response.text
    points = response.json()["points"]
    assert len(points) >= 181
    assert points[-1]["date"] == today.isoformat()
    # 800 salary entries of 100.00 into the bank; 200 card charges of 100.00 into the bank.
    assert Decimal(points[-1]["total_assets"]) == AMOUNT * ENTRY_COUNT
    assert Decimal(points[-1]["total_liabilities"]) == AMOUNT * (ENTRY_COUNT // 5)
    assert statement_count < SERIES_SQL_BUDGET, f"6M daily series issued {statement_count} SQL statements"
    assert elapsed < SERIES_LATENCY_BUDGET_SECONDS, f"6M daily series took {elapsed * 1000:.0f} ms"
