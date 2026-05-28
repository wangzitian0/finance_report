"""AC11.10: Market data sync router tests."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient

from src.routers import market_data as market_data_router
from src.services import market_data


@pytest.mark.asyncio
async def test_market_data_sync_endpoints_return_counts(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.5: Market data sync endpoints return scheduler-friendly counts."""

    async def fake_stock_sync(*_args, **_kwargs) -> market_data.MarketDataSyncResult:
        return market_data.MarketDataSyncResult(
            kind="stock",
            requested=1,
            inserted=1,
            skipped=0,
            missing=0,
            disagreements=[],
        )

    async def fake_fx_sync(*_args, **_kwargs) -> market_data.MarketDataSyncResult:
        return market_data.MarketDataSyncResult(
            kind="fx",
            requested=1,
            inserted=1,
            skipped=0,
            missing=0,
            disagreements=[
                market_data.ProviderDisagreement(
                    asset="USD/SGD",
                    observed_date=date(2026, 1, 5),
                    primary_source="yahoo_finance",
                    secondary_source="stooq",
                    primary_value=Decimal("1.34"),
                    secondary_value=Decimal("1.35"),
                    relative_difference=Decimal("0.007462"),
                    threshold=Decimal("0.02"),
                )
            ],
        )

    monkeypatch.setattr(market_data_router, "sync_stock_prices", fake_stock_sync)
    monkeypatch.setattr(market_data_router, "sync_fx_rates", fake_fx_sync)

    stock_response = await client.post(
        "/market-data/sync/stocks",
        json={
            "symbols": ["AAPL"],
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
    )
    fx_response = await client.post(
        "/market-data/sync/fx",
        json={
            "pairs": ["USD/SGD"],
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
    )

    assert stock_response.status_code == 200
    assert stock_response.json()["inserted"] == 1
    assert stock_response.json()["kind"] == "stock"
    assert fx_response.status_code == 200
    assert fx_response.json()["kind"] == "fx"
    assert fx_response.json()["disagreements"][0]["asset"] == "USD/SGD"


def test_market_data_provider_e2e_gate_is_declared() -> None:
    """AC11.10.7: Provider-backed stock and lazy FX E2E gate is wired as critical."""
    repo_root = Path(__file__).resolve().parents[4]
    e2e_source = (repo_root / "tests/e2e/test_market_data_price_paths.py").read_text()

    assert "@pytest.mark.e2e" in e2e_source
    assert "@pytest.mark.tier3" in e2e_source
    assert "@pytest.mark.critical" in e2e_source
    assert "RUN_MARKET_DATA_PROVIDER_E2E" in e2e_source
    assert "/market-data/sync/stocks" in e2e_source
    assert "/reports/balance-sheet" in e2e_source
