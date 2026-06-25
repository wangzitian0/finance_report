"""Repro for #1388 — report endpoints 500 when the market-data freshness sync raises.

Synthetic data only. Found during real-machine testing of staging v0.1.19:
every money-aggregating report returned HTTP 500 as soon as the account held a
position, while an empty account returned 200. Root cause: the report endpoints
call `_ensure_report_market_data_fresh` -> `ensure_market_data_fresh` (a live
market-data/FX sync) inside a `try` that catches only `ReportError`, so any
other failure from the sync surfaces as a 500.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def account_with_subject(db: AsyncSession, test_user):
    """A single asset account so `_ensure_report_market_data_fresh` actually runs."""
    from src.models.account import Account, AccountType

    account = Account(
        user_id=test_user.id,
        name="Synthetic Brokerage",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.commit()
    return account


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "/reports/balance-sheet",
        "/reports/income-statement?start_date=2025-01-01&end_date=2025-12-31",
        "/reports/cash-flow?start_date=2025-01-01&end_date=2025-12-31",
        "/reports/net-worth/allocation",
        "/reports/net-worth/timeseries?from=2025-01-01&to=2025-12-31",
    ],
)
async def test_reports_do_not_500_when_market_data_sync_raises(
    client: AsyncClient, account_with_subject, monkeypatch, url: str
):
    import src.routers.reports as reports_router

    async def _raise(*args, **kwargs):
        # Mirror a live freshness sync failing on an unresolvable ticker /
        # malformed FX pair with something that is NOT a ReportError.
        raise ValueError("simulated market-data sync failure (unresolvable symbol)")

    monkeypatch.setattr(reports_router, "ensure_market_data_fresh", _raise)

    resp = await client.get(url)
    assert resp.status_code < 500, (
        f"{url} returned {resp.status_code} when the market-data freshness sync "
        "raised a non-ReportError exception; freshness is best-effort and must "
        "not crash report generation with any 5xx"
    )
