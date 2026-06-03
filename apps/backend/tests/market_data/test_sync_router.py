"""AC11.10: Market data sync router tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import FxRate, MarketDataSyncState, StockPrice
from src.routers import market_data as market_data_router, reports as reports_router
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


@pytest.mark.asyncio
async def test_market_data_fx_sync_endpoint_rejects_invalid_pair(client: AsyncClient) -> None:
    """AC11.10.5: FX sync endpoint returns 422 for malformed pair requests."""
    response = await client.post(
        "/market-data/sync/fx",
        json={
            "pairs": ["USD-SGD"],
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
    )

    assert response.status_code == 422
    assert "expected BASE/QUOTE" in response.json()["detail"]


@pytest.mark.asyncio
async def test_market_data_stock_sync_endpoint_rolls_back_service_value_error(
    client: AsyncClient,
    db_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC12.26.3: Stock sync endpoint rolls back when the service rejects a request."""

    async def fake_stock_sync(db: AsyncSession, *_args, **_kwargs) -> market_data.MarketDataSyncResult:
        db.add(
            StockPrice(
                symbol="BAD",
                price=Decimal("1.000000"),
                currency="USD",
                price_date=date(2026, 1, 5),
                source="test",
            )
        )
        await db.flush()
        raise ValueError("invalid symbol")

    monkeypatch.setattr(market_data_router, "sync_stock_prices", fake_stock_sync)

    response = await client.post(
        "/market-data/sync/stocks",
        json={
            "symbols": ["BAD"],
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid symbol"
    sessionmaker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as session:
        persisted = await session.scalar(
            select(StockPrice).where(StockPrice.symbol == "BAD").where(StockPrice.price_date == date(2026, 1, 5))
        )
    assert persisted is None


@pytest.mark.asyncio
async def test_market_data_status_endpoint_returns_authenticated_scope_freshness(
    client: AsyncClient,
    db,
) -> None:
    """AC11.10.11: Authenticated users can inspect market data freshness without triggering sync."""
    observed_at = datetime(2026, 1, 6, tzinfo=UTC)
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=date(2026, 1, 5),
                source="test",
            ),
            StockPrice(
                symbol="IBM",
                price=Decimal("160.000000"),
                currency="USD",
                price_date=date(2026, 1, 5),
                source="test",
            ),
            MarketDataSyncState(
                kind="fx",
                scope="USD/SGD",
                last_success_at=observed_at,
                last_success_date=date(2026, 1, 5),
                last_observation_date=date(2026, 1, 5),
                created_at=observed_at,
                updated_at=observed_at,
            ),
            MarketDataSyncState(
                kind="stock",
                scope="IBM",
                last_success_at=observed_at,
                last_success_date=date(2026, 1, 5),
                last_observation_date=date(2026, 1, 5),
                created_at=observed_at,
                updated_at=observed_at,
            ),
        ]
    )
    await db.commit()

    response = await client.get(
        "/market-data/status",
        params=[("pairs", "USD/SGD"), ("symbols", "IBM")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert {(item["kind"], item["scope"]) for item in payload} == {
        ("fx", "USD/SGD"),
        ("stock", "IBM"),
    }
    assert all(item["last_success_date"] == "2026-01-05" for item in payload)


@pytest.mark.asyncio
async def test_report_endpoint_runs_market_data_freshness_check(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.9: Report reads check market data freshness before generating output."""
    calls: list[str] = []

    async def fake_ensure(
        _db, *, user_id, end_date: date, include_default_fx: bool, extra_fx_pairs: list[str]
    ) -> market_data.MarketDataFreshnessResult:
        calls.append(str(user_id))
        assert end_date == date(2026, 1, 6)
        assert include_default_fx is False
        assert extra_fx_pairs == []
        return market_data.MarketDataFreshnessResult(
            checked_at=datetime(2026, 1, 6, tzinfo=UTC),
            fx=market_data.MarketDataSyncResult(kind="fx"),
            stock=market_data.MarketDataSyncResult(kind="stock"),
        )

    async def fake_balance_sheet(*_args, **_kwargs) -> dict:
        return {
            "as_of_date": date(2026, 1, 6),
            "currency": "SGD",
            "assets": [],
            "liabilities": [],
            "equity": [],
            "total_assets": Decimal("0.00"),
            "total_liabilities": Decimal("0.00"),
            "total_equity": Decimal("0.00"),
            "net_income": Decimal("0.00"),
            "unrealized_fx_gain_loss": Decimal("0.00"),
            "net_worth_adjustment_gain_loss": Decimal("0.00"),
            "fx_warnings": [],
            "equation_delta": Decimal("0.00"),
            "is_balanced": True,
        }

    monkeypatch.setattr(reports_router, "ensure_market_data_fresh", fake_ensure)
    monkeypatch.setattr(reports_router, "generate_balance_sheet", fake_balance_sheet)

    response = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-06"})

    assert response.status_code == 200
    assert calls


def test_report_target_currency_pair_includes_requested_non_base_currency() -> None:
    """AC11.10.9: Report freshness includes the requested target currency scope."""
    assert reports_router._target_currency_pair("USD") == ["USD/SGD"]
    assert reports_router._target_currency_pair("SGD") == []


def test_market_data_provider_e2e_gate_is_declared() -> None:
    """AC11.10.11: Provider-backed user-view E2E gate is wired as critical."""
    repo_root = Path(__file__).resolve().parents[4]
    e2e_source = (repo_root / "tests/e2e/test_market_data_price_paths.py").read_text()

    assert "@pytest.mark.e2e" in e2e_source
    assert "@pytest.mark.tier3" in e2e_source
    assert "@pytest.mark.critical" in e2e_source
    assert "RUN_MARKET_DATA_PROVIDER_E2E" in e2e_source
    assert "/market-data/status" in e2e_source
    assert "/market-data/sync/stocks" not in e2e_source
    assert "/reports/balance-sheet" in e2e_source
