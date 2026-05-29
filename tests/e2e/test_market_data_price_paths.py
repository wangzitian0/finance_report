"""Provider-backed market data E2E paths for lazy FX and stock prices."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import httpx
import pytest

from conftest import AuthState

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
MARKET_DATA_E2E_DATE = date.fromisoformat(
    os.getenv("MARKET_DATA_E2E_DATE", "2024-06-03")
)
MARKET_DATA_PROVIDER_E2E_ENABLED = os.getenv(
    "RUN_MARKET_DATA_PROVIDER_E2E", ""
).lower() in {"1", "true", "yes"}


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.skipif(
    not MARKET_DATA_PROVIDER_E2E_ENABLED,
    reason="RUN_MARKET_DATA_PROVIDER_E2E is not enabled",
)
async def test_market_data_provider_sync_feeds_fx_and_stock_price_paths(
    shared_auth_state: AuthState,
) -> None:
    """AC11.10.7: Lazy FX and stock sync feed portfolio and report valuation paths."""
    headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        import_response = await client.post(
            _api_url("/portfolio/brokerage/import"),
            json={
                "filename": "market-data-provider-e2e.json",
                "source_document_id": f"market-data-provider-e2e-{shared_auth_state.user_id}",
                "payload": {
                    "institution": "Market Data Provider E2E",
                    "statement": {
                        "period_end": MARKET_DATA_E2E_DATE.isoformat(),
                        "currency": "USD",
                    },
                    "positions": [
                        {
                            "symbol": "AAPL",
                            "quantity": "2",
                            "market_value": "20.00",
                            "currency": "USD",
                        }
                    ],
                },
            },
        )
        assert import_response.status_code == 200, (
            f"brokerage import failed: {import_response.status_code} {import_response.text}"
        )
        assert import_response.json()["parsed_positions"] == 1

        stock_response = await client.post(
            _api_url("/market-data/sync/stocks"),
            json={
                "symbols": ["AAPL"],
                "start_date": MARKET_DATA_E2E_DATE.isoformat(),
                "end_date": MARKET_DATA_E2E_DATE.isoformat(),
            },
        )
        assert stock_response.status_code == 200, (
            f"stock sync failed: {stock_response.status_code} {stock_response.text}"
        )
        stock_payload = stock_response.json()
        assert stock_payload["inserted"] + stock_payload["skipped"] >= 1, stock_payload
        assert stock_payload["disagreements"] == []

        holdings_response = await client.get(
            _api_url(
                f"/portfolio/holdings?as_of_date={MARKET_DATA_E2E_DATE.isoformat()}"
            )
        )
        assert holdings_response.status_code == 200, (
            f"holdings failed: {holdings_response.status_code} {holdings_response.text}"
        )
        holdings = holdings_response.json()
        aapl = next(
            (item for item in holdings if item["asset_identifier"] == "AAPL"), None
        )
        assert aapl is not None, f"AAPL holding missing: {holdings}"
        assert _money(aapl["market_value"]) > Decimal("20.00"), (
            f"synced stock price did not replace stale brokerage snapshot: {aapl}"
        )

        report_response = await client.get(
            _api_url(
                f"/reports/balance-sheet?as_of_date={MARKET_DATA_E2E_DATE.isoformat()}&currency=SGD"
            )
        )
        assert report_response.status_code == 200, (
            f"balance sheet failed through lazy FX resolution: {report_response.status_code} {report_response.text}"
        )
        report = report_response.json()
        assert _money(report["total_assets"]) > Decimal("20.00"), report
        assert report["is_balanced"] is True
