import time
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement
from tests.factories import seed_year_of_journal_entries
from tests.reporting._report_fixtures import count_sql_statements

ENTRY_COUNT = 1000
AMOUNT = Decimal("100.00")
LATENCY_BUDGET_SECONDS = 30.0
SERIES_SQL_BUDGET = 30
SERIES_LATENCY_BUDGET_SECONDS = 0.5


def _months_before(value: date, months: int) -> date:
    year, month_index = divmod(value.year * 12 + value.month - 1 - months, 12)
    return date(year, month_index + 1, min(value.day, monthrange(year, month_index + 1)[1]))


async def test_AC5_20_year_scale_reporting_ties_out_within_budget(db: AsyncSession, test_user) -> None:
    await seed_year_of_journal_entries(
        db, test_user.id, first_day=date(2026, 1, 1), entry_count=ENTRY_COUNT, amount=AMOUNT
    )
    p_start, p_end = date(2026, 1, 1), date(2026, 12, 31)
    started = time.perf_counter()
    bs = await generate_balance_sheet(db, test_user.id, as_of_date=p_end, currency="SGD")
    inc = await generate_income_statement(db, test_user.id, start_date=p_start, end_date=p_end, currency="SGD")
    cf = await generate_cash_flow(db, test_user.id, start_date=p_start, end_date=p_end, currency="SGD")
    elapsed = time.perf_counter() - started
    expected_cash = AMOUNT * ENTRY_COUNT
    expected_inc = AMOUNT * (ENTRY_COUNT - ENTRY_COUNT // 5)
    assert (
        inc["total_income"],
        inc["net_income"],
        bs["total_assets"],
        bs["is_balanced"],
        cf["summary"]["ending_cash"],
    ) == (
        expected_inc,
        expected_inc,
        expected_cash,
        True,
        expected_cash,
    )
    assert elapsed < LATENCY_BUDGET_SECONDS


async def test_AC_reporting_net_worth_timeseries_4_six_month_daily_series_within_budget(
    client, db: AsyncSession, db_engine, test_user
) -> None:
    today = date.today()
    await seed_year_of_journal_entries(
        db, test_user.id, first_day=today - timedelta(days=364), entry_count=ENTRY_COUNT, amount=AMOUNT
    )
    params = {
        "from": _months_before(today, 6).isoformat(),
        "to": today.isoformat(),
        "granularity": "daily",
        "currency": "SGD",
    }
    elapsed, stmt_cnt = 999.0, 999
    for _ in range(3):
        with count_sql_statements(db_engine) as stmts:
            started = time.perf_counter()
            resp = await client.get("/reports/net-worth/timeseries", params=params)
            elapsed = min(elapsed, time.perf_counter() - started)
        stmt_cnt = stmts["count"]
        assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) >= 181 and points[-1]["date"] == today.isoformat()
    assert (Decimal(points[-1]["total_assets"]), Decimal(points[-1]["total_liabilities"])) == (
        AMOUNT * ENTRY_COUNT,
        AMOUNT * (ENTRY_COUNT // 5),
    )
    assert stmt_cnt < SERIES_SQL_BUDGET and elapsed < SERIES_LATENCY_BUDGET_SECONDS
