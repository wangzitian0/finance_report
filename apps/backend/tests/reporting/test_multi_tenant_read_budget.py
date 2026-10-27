"""Report reads do not grow with the data of other users (#2617).

Staging holds the data of many throwaway users. At 960 transactions, the balance sheet and the
income statement cost 5 to 30 times what the one-user probe showed. The probe had no other user.
It also measured the CPU of the Python process, not the time of the database. Four defects made a
report read grow with the rows of other users:

* ``NOT EXISTS (... void_reversal_entry_id = journal_entries.id)`` has no index on
  ``void_reversal_entry_id``. Each report statement scanned the journal entries of all users.
* Report statements named the owner of the account only. When the date range was narrow, the
  planner started from the journal entries of all users in that range.
* The FX transfer discovery of the balance sheet and the package had the same shape.
* The classification breakdown joined ``transaction_classification`` to the accounts of the user only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import pytest

from src.reporting import _aggregate_net_income_sql
from tests.query_budget import rows_read_by, seed_other_tenants, seed_tenant_rows

OTHER_TENANTS = 100
OWN_ENTRIES = 150
OWN_TRANSACTIONS = 60
OTHER_ENTRIES = 100
OTHER_TRANSACTIONS = 10
# The rows of other users may change the plan. They may not add a scan of their rows.
GROWTH_FACTOR = 1.25
GROWTH_ALLOWANCE_ROWS = 100

REPORT_PATHS = (
    "/reports/balance-sheet",
    "/reports/income-statement?start_date=2026-01-01&end_date=2026-12-31",
    "/reports/cash-flow?start_date=2026-01-01&end_date=2026-12-31",
    "/reports/net-worth/timeseries?from=2026-01-01&to=2026-12-31&granularity=monthly",
    "/reports/breakdown?type=expense&period=annual",
)
MONTH_TO_DATE_NET_INCOME = "month-to-date net income"


async def _read_all(db, db_engine, client, user_id) -> dict[str, tuple[Any, Any]]:
    """Return ``name -> (rows read per table, result)`` for each read of the budget."""

    def get(path: str) -> Callable[[], Awaitable[Any]]:
        async def action() -> Any:
            response = await client.get(path)
            assert response.status_code == 200, (path, response.status_code, response.text[:300])
            return response.json()

        return action

    async def month_to_date_net_income() -> Any:
        # The advisor and the package read the net income of one month: a narrow date range.
        net_income, _ = await _aggregate_net_income_sql(
            db, user_id, "SGD", date(2026, 1, 31), start_date=date(2026, 1, 1)
        )
        return str(net_income)

    actions = {path: get(path) for path in REPORT_PATHS}
    actions[MONTH_TO_DATE_NET_INCOME] = month_to_date_net_income
    return {name: await rows_read_by(db_engine, action) for name, action in actions.items()}


@pytest.mark.asyncio
async def test_AC_reporting_2617_1_report_reads_do_not_grow_with_other_tenants(
    db, db_engine, client, test_user
) -> None:
    """AC-reporting.2617.1: with 100 more users in the database, each report read reads at most
    1.25 times the rows (plus 100) that it reads when the database holds one user. Its result
    for the user does not change.

    Rows are counted from ``EXPLAIN (ANALYZE)`` of each SELECT with sequential scans off, so that
    a missing index shows as a scan of the table.
    """
    user_id = test_user.id
    await seed_tenant_rows(db, user_id, entries=OWN_ENTRIES, transactions=OWN_TRANSACTIONS)
    alone = await _read_all(db, db_engine, client, user_id)

    await seed_other_tenants(db, count=OTHER_TENANTS, entries=OTHER_ENTRIES, transactions=OTHER_TRANSACTIONS)
    shared = await _read_all(db, db_engine, client, user_id)

    violations = []
    for name, (own_by_table, own_result) in alone.items():
        shared_by_table, shared_result = shared[name]
        assert shared_result == own_result, f"{name} changed when other users were added"
        assert own_result, f"{name} returned an empty result"
        own_rows = sum(own_by_table.values())
        shared_rows = sum(shared_by_table.values())
        assert own_rows > 0, f"{name} read no row: the budget would pass on an empty read"
        if shared_rows > GROWTH_FACTOR * own_rows + GROWTH_ALLOWANCE_ROWS:
            violations.append(
                f"{name} reads {shared_rows} rows with {OTHER_TENANTS} other users and {own_rows} rows alone. "
                f"By table, alone: {_nonzero(own_by_table)}; shared: {_nonzero(shared_by_table)}"
            )
    assert not violations, "\n".join(violations)


def _nonzero(rows_by_table) -> dict[str, int]:
    return {table: rows for table, rows in rows_by_table.items() if rows}
