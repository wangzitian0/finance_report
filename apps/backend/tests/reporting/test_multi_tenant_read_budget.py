from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from src.reporting import _aggregate_net_income_sql
from tests.query_budget import rows_read_by, seed_other_tenants, seed_tenant_rows

_ANALYZE_SQL = text(
    "ANALYZE accounts, journal_entries, journal_lines, atomic_transactions, "
    "transaction_classification, classification_rules, reconciliation_matches, "
    "statement_summaries, uploaded_documents"
)


async def _analyze_budget_tables(db_engine) -> None:
    async with db_engine.connect() as conn:
        await (await conn.execution_options(isolation_level="AUTOCOMMIT")).execute(_ANALYZE_SQL)


BASELINE_OTHER_TENANTS = 10
OTHER_TENANTS = 100
GROWTH_FACTOR = 1.25
GROWTH_ALLOWANCE_ROWS = 100
REPORT_PATHS = (
    "/reports/balance-sheet",
    "/reports/income-statement?start_date=2026-01-01&end_date=2026-12-31",
    "/reports/cash-flow?start_date=2026-01-01&end_date=2026-12-31",
    "/reports/net-worth/timeseries?from=2026-01-01&to=2026-12-31&granularity=monthly",
)


async def _read_all(db, db_engine, client, user_id) -> dict[str, tuple[dict[str, int], Any]]:
    async def get(path: str) -> Any:
        resp = await client.get(path)
        assert resp.status_code == 200, (path, resp.status_code, resp.text[:300])
        return resp.json()

    actions = {path: (lambda p=path: get(p)) for path in REPORT_PATHS}
    actions["month-to-date net income"] = lambda: _aggregate_net_income_sql(
        db, user_id, "SGD", date(2026, 1, 31), start_date=date(2026, 1, 1)
    )
    return {name: await rows_read_by(db_engine, action) for name, action in actions.items()}


async def test_AC_reporting_2617_1_report_reads_do_not_grow_with_other_tenants(
    db, db_engine, client, test_user
) -> None:
    await seed_tenant_rows(db, test_user.id, entries=150, transactions=60)
    await seed_other_tenants(db, count=BASELINE_OTHER_TENANTS, entries=100, transactions=10)
    await _analyze_budget_tables(db_engine)
    alone = await _read_all(db, db_engine, client, test_user.id)
    await seed_other_tenants(db, count=OTHER_TENANTS, entries=100, transactions=10)
    await _analyze_budget_tables(db_engine)
    shared = await _read_all(db, db_engine, client, test_user.id)
    for name, (own_by_table, own_res) in alone.items():
        shared_by_table, shared_res = shared[name]
        own_rows, shared_rows = sum(own_by_table.values()), sum(shared_by_table.values())
        assert shared_res == own_res and own_res and own_rows > 0, name
        assert shared_rows <= GROWTH_FACTOR * own_rows + GROWTH_ALLOWANCE_ROWS, (name, own_rows, shared_rows)
