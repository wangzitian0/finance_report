from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src import composition
from src.platform import PreconditionFailedError
from src.pricing.extension import market_data
from src.pricing.orm.market_data import FxRate, MarketDataSyncState, StockPrice
from src.routers import pricing as pricing_router, reports as reports_router


async def test_market_data_sync_endpoints_and_validation(client: AsyncClient, db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    bad_fx = await client.post("/pricing/fx/syncs", json={"pairs": ["USD-SGD"], "start_date": "2026-01-05", "end_date": "2026-01-05"})
    dis = market_data.ProviderDisagreement("USD/SGD", date(2026, 1, 5), "yahoo_finance", "stooq", Decimal("1.34"), Decimal("1.35"), Decimal("0.007462"), Decimal("0.02"))
    monkeypatch.setattr(pricing_router, "sync_stock_prices", lambda *_a, **_kw: _coro(market_data.MarketDataSyncResult(kind="stock", requested=1, inserted=1)))
    monkeypatch.setattr(pricing_router, "sync_fx_rates", lambda *_a, **_kw: _coro(market_data.MarketDataSyncResult(kind="fx", requested=1, inserted=1, disagreements=[dis])))
    stock_resp = await client.post("/pricing/stocks/syncs", json={"symbols": ["AAPL"], "start_date": "2026-01-05", "end_date": "2026-01-05"})
    fx_resp = await client.post("/pricing/fx/syncs", json={"pairs": ["USD/SGD"], "start_date": "2026-01-05", "end_date": "2026-01-05"})

    async def fail_stock(db: AsyncSession, *_a, **_kw):
        db.add(StockPrice(symbol="BAD", price=Decimal("1.000000"), currency="USD", price_date=date(2026, 1, 5), source="test"))
        await db.flush()
        raise PreconditionFailedError("invalid symbol")

    monkeypatch.setattr(pricing_router, "sync_stock_prices", fail_stock)
    bad_stock = await client.post("/pricing/stocks/syncs", json={"symbols": ["BAD"], "start_date": "2026-01-05", "end_date": "2026-01-05"})
    async with async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)() as session:
        persisted = await session.scalar(select(StockPrice).where(StockPrice.symbol == "BAD", StockPrice.price_date == date(2026, 1, 5)))
    assert (
        (stock_resp.status_code, stock_resp.json()["inserted"], stock_resp.json()["kind"]),
        (fx_resp.status_code, fx_resp.json()["kind"], fx_resp.json()["disagreements"][0]["asset"]),
        (bad_fx.status_code, "expected BASE/QUOTE" in bad_fx.json()["detail"]),
        (bad_stock.status_code, bad_stock.json()["detail"], persisted),
    ) == ((200, 1, "stock"), (200, "fx", "USD/SGD"), (422, True), (422, "invalid symbol", None))


async def _coro(v):
    return v


async def test_market_data_status_and_freshness_read_only_boundary(client: AsyncClient, db, monkeypatch: pytest.MonkeyPatch) -> None:
    obs_at = datetime(2026, 1, 6, tzinfo=UTC)
    db.add_all([
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=date(2026, 1, 5), source="test"),
        StockPrice(symbol="IBM", price=Decimal("160.000000"), currency="USD", price_date=date(2026, 1, 5), source="test"),
        MarketDataSyncState(kind="fx", scope="USD/SGD", last_success_at=obs_at, last_success_date=date(2026, 1, 5), last_observation_date=date(2026, 1, 5), created_at=obs_at, updated_at=obs_at),
        MarketDataSyncState(kind="stock", scope="IBM", last_success_at=obs_at, last_success_date=date(2026, 1, 5), last_observation_date=date(2026, 1, 5), created_at=obs_at, updated_at=obs_at),
    ])
    await db.commit()
    status_resp = await client.get("/pricing/market-data/status", params=[("pairs", "USD/SGD"), ("symbols", "IBM")])

    calls: list[tuple[list[str], list[str], date]] = []

    async def fake_ensure(_db, *, fx_pairs, stock_symbols, end_date: date):
        calls.append((sorted(fx_pairs), sorted(stock_symbols), end_date))
        return market_data.MarketDataFreshnessResult(checked_at=obs_at, fx=market_data.MarketDataSyncResult(kind="fx"), stock=market_data.MarketDataSyncResult(kind="stock"))

    monkeypatch.setattr(composition.settings, "market_data_lazy_fetch_enabled", True)
    monkeypatch.setattr(composition, "ensure_market_data_fresh", fake_ensure)
    monkeypatch.setattr(reports_router, "generate_balance_sheet", lambda *_a, **_kw: _coro({"as_of_date": date(2026, 1, 6), "currency": "SGD", "assets": [], "liabilities": [], "equity": [], "total_assets": Decimal("0.00"), "total_liabilities": Decimal("0.00"), "total_equity": Decimal("0.00"), "net_income": Decimal("0.00"), "unrealized_fx_gain_loss": Decimal("0.00"), "net_worth_adjustment_gain_loss": Decimal("0.00"), "fx_warnings": [], "equation_delta": Decimal("0.00"), "is_balanced": True}))
    imp = await client.post("/portfolio/brokerage-imports", json={"filename": "sync-check.json", "payload": {"institution": "Sync Broker", "statement": {"period_end": "2026-01-06", "currency": "USD"}, "positions": [{"symbol": "AAPL", "quantity": "1", "market_value": "100.00", "currency": "USD"}]}})
    calls_after_import = list(calls)
    calls.clear()
    rep = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-06"})
    e2e_src = (Path(__file__).resolve().parents[4] / "tests/e2e/test_market_data_price_paths.py").read_text()
    assert (
        (status_resp.status_code, {(i["kind"], i["scope"]) for i in status_resp.json()}, all(i["last_success_date"] == "2026-01-05" for i in status_resp.json())),
        (imp.status_code, calls_after_import, rep.status_code, calls, hasattr(reports_router, "_ensure_report_market_data_fresh")),
        ("@pytest.mark.e2e" in e2e_src, "@pytest.mark.tier3" in e2e_src, "@pytest.mark.critical" in e2e_src, "RUN_MARKET_DATA_PROVIDER_E2E" in e2e_src, "/pricing/market-data/status" in e2e_src, "/pricing/stocks/syncs" not in e2e_src, "/reports/balance-sheet" in e2e_src),
    ) == ((200, {("fx", "USD/SGD"), ("stock", "IBM")}, True), (200, [(["USD/SGD"], ["AAPL"], date(2026, 1, 6))], 200, [], False), (True, True, True, True, True, True, True))
