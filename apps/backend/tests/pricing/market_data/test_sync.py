from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.composition import market_data_scopes, observed_fx_pairs
from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalLine
from src.portfolio import PortfolioService, active_stock_symbols
from src.portfolio.orm.portfolio import CostBasisMethod, InvestmentTransaction, InvestmentTransactionType, ManagedPosition, PositionStatus
from src.pricing.extension import market_data
from src.pricing.orm.market_data import FxRate, MarketDataSyncState, StockPrice


def _dates(dates):
    return dates if isinstance(dates, list) else list(market_data._iter_dates(dates[0], dates[1])) if isinstance(dates, tuple) else []


def _make_stock_series(symbol: str, dates=None, price: Decimal = Decimal("150.1234564"), currency: str = "USD", source: str = "test_primary"):
    return market_data.ValidatedMarketObservationSeries(observations=[market_data.StockPriceObservation(symbol=symbol, price=price, currency=currency, price_date=d, source=source) for d in _dates(dates)])


def _make_fx_series(base: str, quote: str, dates=None, rate: Decimal = Decimal("1.350000"), source: str = "test_primary"):
    return market_data.ValidatedMarketObservationSeries(observations=[market_data.FxRateObservation(base_currency=base, quote_currency=quote, rate=rate, rate_date=d, source=source) for d in _dates(dates)])


def _pos(user_id, account_id, asset_identifier, quantity=Decimal("2"), cost_basis=Decimal("100.00"), currency="USD", status=PositionStatus.ACTIVE):
    return ManagedPosition(user_id=user_id, account_id=account_id, asset_identifier=asset_identifier, quantity=quantity, cost_basis=cost_basis, currency=currency, acquisition_date=date(2026, 1, 1), status=status, cost_basis_method=CostBasisMethod.FIFO)


def _buy_row(user_id, position, cost: Decimal) -> InvestmentTransaction:
    """A recorded purchase: the only source of a cost basis at a past date (#2920)."""
    return InvestmentTransaction(user_id=user_id, position_id=position.id, transaction_date=date(2026, 1, 2), transaction_type=InvestmentTransactionType.BUY, asset_identifier=position.asset_identifier, quantity=position.quantity, unit_price=(cost / position.quantity).quantize(Decimal("0.0001")), gross_amount=cost, fees=Decimal("0.00"), currency=position.currency, cost_basis=cost)


async def test_sync_stock_prices_idempotent_decade_missing_skip_and_disagreement(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    d5, d6, d10 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 10)
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda sym, s, e: _coro(_make_stock_series(sym, (s, e))))
    first = await market_data.sync_stock_prices(db, symbols=["aapl"], start_date=d5, end_date=d6)
    second = await market_data.sync_stock_prices(db, symbols=["AAPL"], start_date=d5, end_date=d6)
    latest = await db.scalar(select(StockPrice).where(StockPrice.symbol == "AAPL", StockPrice.price_date == d6))
    calls: list[tuple[str, date, date]] = []

    async def decade_fetch(sym: str, s: date, e: date):
        calls.append((sym, s, e))
        return market_data.ValidatedMarketObservationSeries(observations=[market_data.StockPriceObservation(sym, Decimal("100.000000"), "USD", s, "test_primary"), market_data.StockPriceObservation(sym, Decimal("200.000000"), "USD", e, "test_primary")])

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", decade_fetch)
    dec_start, dec_end = date(2016, 1, 1), date(2026, 1, 1)
    dec = await market_data.sync_stock_prices(db, symbols=["IBM"], start_date=dec_start, end_date=dec_end)
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda *_a: _coro(market_data.ValidatedMarketObservationSeries(observations=[])))
    miss = await market_data.sync_stock_prices(db, symbols=["MSFT"], start_date=d10, end_date=d10)
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda *_a: _coro((_ for _ in ()).throw(AssertionError("completed ranges should not call the provider"))))
    done = await market_data.sync_stock_prices(db, symbols=["", "AAPL"], end_date=d5)
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda sym, s, _e: _coro(market_data.ValidatedMarketObservationSeries(disagreements=[market_data.ProviderDisagreement(sym, s, "yahoo_finance", "stooq", Decimal("100.00"), Decimal("112.00"), Decimal("0.12"), Decimal("0.02"))])))
    dis = await market_data.sync_stock_prices(db, symbols=["MSFT"], start_date=d5, end_date=d5)
    assert (
        (first.inserted, first.skipped, first.missing, second.inserted, second.skipped, second.missing),
        (await db.scalar(select(func.count()).select_from(StockPrice).where(StockPrice.symbol == "AAPL")), latest.price, latest.currency, repr(latest)),
        (calls, dec.inserted, dec.requested, await db.scalar(select(func.count()).select_from(StockPrice).where(StockPrice.symbol == "IBM"))),
        (miss.inserted, miss.missing, miss.disagreements, done.requested, done.inserted),
        (dis.inserted, dis.missing, len(dis.disagreements), dis.disagreements[0].asset, await db.scalar(select(func.count()).select_from(StockPrice).where(StockPrice.symbol == "MSFT"))),
    ) == (
        (2, 0, 0, 0, 2, 0),
        (2, Decimal("150.123456"), "USD", "<StockPrice AAPL 150.123456 USD 2026-01-06>"),
        ([("IBM", dec_start, dec_end)], 2, len(market_data._iter_dates(dec_start, dec_end)), 2),
        (0, 1, [], 0, 0),
        (0, 0, 1, "MSFT", 0),
    )


async def _coro(value):
    return value


async def test_sync_fx_rates_incremental_skip_missing_disagreement_and_default_pairs(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    d5, d6 = date(2026, 1, 5), date(2026, 1, 6)
    requested: list[tuple[str, str, date, date]] = []

    async def fake_fx(base: str, quote: str, s: date, e: date):
        requested.append((base, quote, s, e))
        return _make_fx_series(base, quote, (s, e))

    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", fake_fx)
    default_res = await market_data.sync_fx_rates(db, pairs=(await market_data_scopes(db)).fx_pairs, start_date=d5, end_date=d5)
    assert (requested, default_res.inserted) == ([("USD", "SGD", d5, d5)], 1)
    requested.clear()
    inc_res = await market_data.sync_fx_rates(db, pairs=["USD/SGD"], start_date=date(2026, 1, 1), end_date=d6)
    db.add(FxRate(base_currency="CAD", quote_currency="SGD", rate=Decimal("1.010000"), rate_date=d6, source="seed"))
    await db.commit()
    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", lambda b, q, s, _e: _coro(market_data.ValidatedMarketObservationSeries(disagreements=[market_data.ProviderDisagreement(f"{b}/{q}", s, "yahoo_finance", "stooq", Decimal("1.00"), Decimal("1.10"), Decimal("0.10"), Decimal("0.02"))]) if b == "EUR" else market_data.ValidatedMarketObservationSeries(observations=[])))
    mixed = await market_data.sync_fx_rates(db, pairs=["SGD/SGD", "USD/SGD", "HKD/SGD", "EUR/SGD"], start_date=d5, end_date=d5)
    empty = await market_data.sync_fx_rates(db, pairs=["CAD/SGD"], end_date=d5)
    assert (requested, inc_res.inserted, inc_res.skipped, await db.scalar(select(func.count()).select_from(FxRate).where(FxRate.base_currency == "USD")), (mixed.skipped, mixed.missing, mixed.inserted, len(mixed.disagreements)), empty.requested) == (
        [("USD", "SGD", d6, d6)],
        1,
        0,
        2,
        (1, 1, 0, 1),
        0,
    )


async def test_sync_ignores_mismatched_observation_types(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    d5 = date(2026, 1, 5)
    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", lambda _b, _q, s, _e: _coro(_make_stock_series("AAPL", [s], price=Decimal("100.000000"), source="bad_provider")))
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda _sym, s, _e: _coro(_make_fx_series("USD", "SGD", [s], rate=Decimal("1.350000"), source="bad_provider")))
    fx_res = await market_data.sync_fx_rates(db, pairs=["USD/SGD"], start_date=d5, end_date=d5)
    stock_res = await market_data.sync_stock_prices(db, symbols=["AAPL"], start_date=d5, end_date=d5)
    assert (fx_res.inserted, fx_res.missing, stock_res.inserted, stock_res.missing) == (0, 1, 0, 1)


async def test_observed_fx_pairs_and_active_stock_symbols(db: AsyncSession, test_user) -> None:
    acct = Account(user_id=test_user.id, name="HKD Cash", type=AccountType.ASSET, currency="HKD")
    db.add(acct)
    await db.flush()
    assert await observed_fx_pairs(db, test_user.id) == ["HKD/SGD", "USD/SGD"]
    entry = JournalEntry(user_id=test_user.id, entry_date=date(2026, 1, 5), memo="JPY spend")
    db.add(entry)
    await db.flush()
    db.add_all([
        JournalLine(journal_entry_id=entry.id, account_id=acct.id, direction=Direction.DEBIT, amount=Decimal("100.00"), currency="JPY"),
        _pos(test_user.id, acct.id, "VWRA", quantity=Decimal("2"), currency="EUR"),
        _pos(test_user.id, acct.id, "aapl", quantity=Decimal("2")),
        _pos(test_user.id, acct.id, "MSFT", quantity=Decimal("0"), cost_basis=Decimal("0.00")),
        _pos(test_user.id, acct.id, "TSLA", quantity=Decimal("1"), status=PositionStatus.DISPOSED),
        AtomicPosition(user_id=test_user.id, snapshot_date=date(2026, 1, 5), asset_identifier="VWRA", broker="Test Broker", quantity=Decimal("2"), market_value=Decimal("100.00"), currency="GBP", dedup_hash="vwra-gbp-snapshot", source_documents={}),
    ])
    await db.commit()
    assert (await observed_fx_pairs(db, test_user.id), await active_stock_symbols(db, test_user.id)) == (["EUR/SGD", "GBP/SGD", "HKD/SGD", "JPY/SGD", "USD/SGD"], ["AAPL", "VWRA"])


async def test_portfolio_uses_and_quantizes_synced_stock_prices(db: AsyncSession, test_user) -> None:
    acct = Account(user_id=test_user.id, name="Brokerage", type=AccountType.ASSET, currency="SGD")
    db.add(acct)
    await db.flush()
    aapl, ibm = _pos(test_user.id, acct.id, "AAPL", quantity=Decimal("2"), currency="SGD"), _pos(test_user.id, acct.id, "IBM", quantity=Decimal("3"), cost_basis=Decimal("26.90"), currency="SGD")
    db.add_all([
        aapl,
        AtomicPosition(user_id=test_user.id, snapshot_date=date(2026, 1, 5), asset_identifier="AAPL", broker="Test Broker", quantity=Decimal("2"), market_value=Decimal("100.00"), currency="SGD", dedup_hash="aapl-stale-snapshot", source_documents={}),
        StockPrice(symbol="AAPL", price=Decimal("155.000000"), currency="SGD", price_date=date(2026, 1, 6), source="test_sync"),
        ibm,
        AtomicPosition(user_id=test_user.id, snapshot_date=date(2026, 1, 5), asset_identifier="IBM", broker="Test Broker", quantity=Decimal("3"), market_value=Decimal("300.00"), currency="SGD", dedup_hash="ibm-decimal-snapshot", source_documents={}),
        StockPrice(symbol="IBM", price=Decimal("173.980232"), currency="SGD", price_date=date(2026, 1, 6), source="test_sync"),
    ])
    await db.flush()
    db.add_all([_buy_row(test_user.id, aapl, Decimal("100.00")), _buy_row(test_user.id, ibm, Decimal("26.90"))])
    await db.commit()
    by_sym = {h.asset_identifier: h for h in await PortfolioService().get_holdings(db, user_id=test_user.id, as_of_date=date(2026, 1, 6), base_currency="SGD")}
    assert ((by_sym["AAPL"].market_value, by_sym["AAPL"].unrealized_pnl), (by_sym["IBM"].market_value, by_sym["IBM"].unrealized_pnl)) == ((Decimal("310.00"), Decimal("210.00")), (Decimal("521.94"), Decimal("495.04")))  # cost from the recorded BUY rows (#2920)


async def test_persist_stock_price_and_upsert_sync_state_concurrency(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    db.add(StockPrice(symbol="AAPL", price=Decimal("150.000000"), currency="USD", price_date=date(2026, 1, 5), source="seed"))
    await db.commit()
    assert await market_data._persist_stock_price(db, market_data.StockPriceObservation("aapl", Decimal("160.000000"), "USD", date(2026, 1, 5), "new")) == Decimal("150.000000")

    class NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    class FakeDb:
        flushes = 0
        fail_always = False

        def add(self, _row):
            return None

        async def flush(self):
            self.flushes += 1
            if self.fail_always or self.flushes == 1:
                raise IntegrityError("insert", {}, Exception("duplicate"))

        async def rollback(self):
            return None

        def begin_nested(self):
            return NestedTransaction()

    err_db = FakeDb()
    err_db.fail_always = True
    monkeypatch.setattr(market_data._store, "_load_stored_stock_price_on_date", lambda *_a: _coro(None))
    with pytest.raises(IntegrityError):
        await market_data._persist_stock_price(err_db, market_data.StockPriceObservation("AAPL", Decimal("160.000000"), "USD", date(2026, 1, 5), "new"))

    state = type("_State", (), {"last_success_at": datetime(2026, 1, 4, tzinfo=UTC), "last_success_date": date(2026, 1, 4), "last_observation_date": date(2026, 1, 4), "updated_at": datetime(2026, 1, 4, tzinfo=UTC)})()
    calls = 0

    async def fake_load_state(_db, _kind, _scope):
        nonlocal calls
        calls += 1
        return None if calls == 1 else state

    monkeypatch.setattr(market_data._store, "_load_sync_state", fake_load_state)
    obs_now = datetime(2026, 1, 6, tzinfo=UTC)
    ok_db = FakeDb()
    await market_data._upsert_sync_state(ok_db, kind="stock", scope="AAPL", last_success_date=date(2026, 1, 6), last_observation_date=date(2026, 1, 5), now=obs_now)
    assert (ok_db.flushes, state.last_success_at, state.last_success_date) == (2, obs_now, date(2026, 1, 6))


async def test_market_data_freshness_sync_backfill_and_same_currency_skip(db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch) -> None:
    acct = Account(user_id=test_user.id, name="USD Brokerage", type=AccountType.ASSET, currency="USD")
    db.add(acct)
    await db.flush()
    stale_at = datetime(2026, 1, 4, 0, 0, tzinfo=UTC)
    fresh_at = datetime(2026, 1, 6, 8, 0, tzinfo=UTC)
    db.add_all([
        _pos(test_user.id, acct.id, "AAPL", quantity=Decimal("1"), currency="USD"),
        _pos(test_user.id, acct.id, "IBM", quantity=Decimal("1"), currency="SGD"),
        StockPrice(symbol="IBM", price=Decimal("200.000000"), currency="USD", price_date=date(2026, 1, 6), source="future_seed"),
        MarketDataSyncState(kind="fx", scope="USD/SGD", last_success_at=stale_at, last_success_date=date(2026, 1, 4), last_observation_date=date(2026, 1, 4), created_at=stale_at, updated_at=stale_at),
        MarketDataSyncState(kind="stock", scope="AAPL", last_success_at=stale_at, last_success_date=date(2026, 1, 4), last_observation_date=date(2026, 1, 4), created_at=stale_at, updated_at=stale_at),
        MarketDataSyncState(kind="stock", scope="IBM", last_success_at=fresh_at, last_success_date=date(2026, 1, 6), last_observation_date=date(2026, 1, 6), created_at=fresh_at, updated_at=fresh_at),
    ])
    await db.commit()
    ranges: list[tuple[str, date, date]] = []
    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", lambda b, q, s, e: _coro(_make_fx_series(b, q, (s, e))))
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda sym, s, e: (ranges.append((sym, s, e)), _coro(_make_stock_series(sym, (s, e), price=Decimal("200.000000"))))[1])
    fx_pairs, syms = await observed_fx_pairs(db, test_user.id), await active_stock_symbols(db, test_user.id)
    first = await market_data.ensure_market_data_fresh(db, fx_pairs=fx_pairs, stock_symbols=syms, end_date=date(2026, 1, 6), now=fresh_at)
    second = await market_data.ensure_market_data_fresh(db, fx_pairs=fx_pairs, stock_symbols=syms, end_date=date(2026, 1, 6), now=fresh_at + timedelta(hours=1))
    ranges.clear()
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda sym, s, e: (ranges.append((sym, s, e)), _coro(_make_stock_series(sym, [e], price=Decimal("150.000000"))))[1])
    backfill = await market_data.ensure_market_data_fresh(db, fx_pairs=fx_pairs, stock_symbols=["IBM"], end_date=date(2024, 6, 3), now=datetime(2026, 1, 6, 9, 0, tzinfo=UTC))
    monkeypatch.setattr(market_data.service, "sync_fx_rates", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("same-currency scope should not sync")))
    same_ccy = await market_data.ensure_market_data_fresh(db, fx_pairs=["SGD/SGD"], stock_symbols=[], end_date=date(2026, 1, 5))
    assert (first.triggered, first.fx.requested > 0, first.stock.requested > 0, second.triggered, backfill.triggered, ranges, backfill.stock.inserted, same_ccy.triggered) == (True, True, True, False, True, [("IBM", date(2024, 5, 28), date(2024, 6, 3))], 1, False)


async def test_market_data_sync_state_and_status_observation_fallback(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda *_a: _coro(market_data.ValidatedMarketObservationSeries(observations=[], provider_success=True)))
    res = await market_data.sync_stock_prices(db, symbols=["AAPL"], start_date=date(2026, 1, 10), end_date=date(2026, 1, 11))
    state = await db.scalar(select(MarketDataSyncState).where(MarketDataSyncState.kind == "stock", MarketDataSyncState.scope == "AAPL"))
    assert (res.inserted, res.missing, state.last_success_date) == (0, 2, date(2026, 1, 11))
    empty_status = await market_data.get_market_data_status(db, pairs=[], symbols=["AAPL"], now=datetime(2026, 1, 11, 1, 0, tzinfo=UTC))
    db.add(StockPrice(symbol="AAPL", price=Decimal("190.000000"), currency="USD", price_date=date(2026, 1, 10), source="test"))
    await db.commit()
    fb_status = await market_data.get_market_data_status(db, pairs=[], symbols=["AAPL"], now=datetime(2026, 1, 11, 1, 0, tzinfo=UTC))
    assert ((len(empty_status), empty_status[0].fresh, empty_status[0].last_observation_date), (len(fb_status), fb_status[0].fresh, fb_status[0].last_observation_date)) == ((1, False, None), (1, True, date(2026, 1, 10)))
