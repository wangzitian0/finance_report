"""AC11.10: Daily market data sync tests."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.pricing.extension import market_data
from src.pricing.orm.market_data import FxRate, MarketDataSyncState, StockPrice
from src.services.market_data_discovery import active_stock_symbols, observed_fx_pairs
from src.services.portfolio import PortfolioService


async def test_sync_stock_prices_inserts_missing_daily_rows_and_is_idempotent(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.1: AC11.10.1: Stock sync stores daily rows once and skips existing rows on rerun."""

    async def fake_fetch(symbol: str, start_date: date, end_date: date) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.StockPriceObservation(
                    symbol=symbol,
                    price=Decimal("150.1234564"),
                    currency="USD",
                    price_date=requested_date,
                    source="test_primary",
                )
                for requested_date in market_data._iter_dates(start_date, end_date)
            ]
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_fetch)

    first = await market_data.sync_stock_prices(
        db,
        symbols=["aapl"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
    )
    second = await market_data.sync_stock_prices(
        db,
        symbols=["AAPL"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
    )

    assert first.inserted == 2
    assert first.skipped == 0
    assert first.missing == 0
    assert second.inserted == 0
    assert second.skipped == 2
    assert second.missing == 0

    count = await db.scalar(select(func.count()).select_from(StockPrice).where(StockPrice.symbol == "AAPL"))
    assert count == 2
    latest = await db.scalar(
        select(StockPrice).where(StockPrice.symbol == "AAPL").where(StockPrice.price_date == date(2026, 1, 6))
    )
    assert latest is not None
    assert latest.price == Decimal("150.123456")
    assert latest.currency == "USD"
    assert repr(latest) == "<StockPrice AAPL 150.123456 USD 2026-01-06>"


async def test_sync_stock_prices_fetches_decade_range_once(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.8: AC11.10.8: Long history sync uses one provider range request per symbol."""
    start = date(2016, 1, 1)
    end = date(2026, 1, 1)
    calls: list[tuple[str, date, date]] = []

    async def fake_fetch(symbol: str, start_date: date, end_date: date) -> market_data.ValidatedMarketObservationSeries:
        calls.append((symbol, start_date, end_date))
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.StockPriceObservation(
                    symbol=symbol,
                    price=Decimal("100.000000"),
                    currency="USD",
                    price_date=start_date,
                    source="test_primary",
                ),
                market_data.StockPriceObservation(
                    symbol=symbol,
                    price=Decimal("200.000000"),
                    currency="USD",
                    price_date=end_date,
                    source="test_primary",
                ),
            ]
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_fetch)

    result = await market_data.sync_stock_prices(db, symbols=["AAPL"], start_date=start, end_date=end)

    assert calls == [("AAPL", start, end)]
    assert result.inserted == 2
    assert result.requested == len(market_data._iter_dates(start, end))
    count = await db.scalar(select(func.count()).select_from(StockPrice).where(StockPrice.symbol == "AAPL"))
    assert count == 2


async def test_sync_fx_rates_starts_after_last_stored_date(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.2: AC11.10.2: FX sync starts after the last stored date for each explicit pair."""
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.340000"),
            rate_date=date(2026, 1, 5),
            source="seed",
        )
    )
    await db.commit()
    requested: list[tuple[str, str, date, date]] = []

    async def fake_fetch(
        base: str, quote: str, start_date: date, end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        requested.append((base, quote, start_date, end_date))
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.FxRateObservation(
                    base_currency=base,
                    quote_currency=quote,
                    rate=Decimal("1.350000"),
                    rate_date=requested_date,
                    source="test_primary",
                )
                for requested_date in market_data._iter_dates(start_date, end_date)
            ]
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", fake_fetch)

    result = await market_data.sync_fx_rates(
        db,
        pairs=["USD/SGD"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 6),
    )

    assert requested == [("USD", "SGD", date(2026, 1, 6), date(2026, 1, 6))]
    assert result.inserted == 1
    assert result.skipped == 0
    count = await db.scalar(select(func.count()).select_from(FxRate).where(FxRate.base_currency == "USD"))
    assert count == 2


async def test_sync_fx_rates_reports_skip_missing_disagreement_and_empty_work(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.3: FX sync exposes skipped, missing, and disagreement rows without aborting."""
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.340000"),
                rate_date=date(2026, 1, 5),
                source="seed",
            ),
            FxRate(
                base_currency="CAD",
                quote_currency="SGD",
                rate=Decimal("1.010000"),
                rate_date=date(2026, 1, 6),
                source="seed",
            ),
        ]
    )
    await db.commit()

    async def fake_fetch(
        base: str, quote: str, start_date: date, _end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        if base == "EUR":
            return market_data.ValidatedMarketObservationSeries(
                disagreements=[
                    market_data.ProviderDisagreement(
                        asset=f"{base}/{quote}",
                        observed_date=start_date,
                        primary_source="yahoo_finance",
                        secondary_source="stooq",
                        primary_value=Decimal("1.00"),
                        secondary_value=Decimal("1.10"),
                        relative_difference=Decimal("0.10"),
                        threshold=Decimal("0.02"),
                    )
                ],
            )
        return market_data.ValidatedMarketObservationSeries(observations=[])

    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", fake_fetch)

    result = await market_data.sync_fx_rates(
        db,
        pairs=["SGD/SGD", "USD/SGD", "HKD/SGD", "EUR/SGD"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
    )
    empty = await market_data.sync_fx_rates(
        db,
        pairs=["CAD/SGD"],
        end_date=date(2026, 1, 5),
    )

    assert result.skipped == 1
    assert result.missing == 1
    assert result.inserted == 0
    assert len(result.disagreements) == 1
    assert empty.requested == 0


async def test_sync_ignores_mismatched_observation_types(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.4: Sync ignores provider observations with the wrong market data kind."""

    async def fake_stock_observation_for_fx(
        _base: str,
        _quote: str,
        start_date: date,
        _end_date: date,
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.StockPriceObservation(
                    symbol="AAPL",
                    price=Decimal("100.000000"),
                    currency="USD",
                    price_date=start_date,
                    source="bad_provider",
                )
            ]
        )

    async def fake_fx_observation_for_stock(
        _symbol: str,
        start_date: date,
        _end_date: date,
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.FxRateObservation(
                    base_currency="USD",
                    quote_currency="SGD",
                    rate=Decimal("1.350000"),
                    rate_date=start_date,
                    source="bad_provider",
                )
            ]
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", fake_stock_observation_for_fx)
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_fx_observation_for_stock)

    fx_result = await market_data.sync_fx_rates(
        db,
        pairs=["USD/SGD"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
    )
    stock_result = await market_data.sync_stock_prices(
        db,
        symbols=["AAPL"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
    )

    assert fx_result.inserted == 0
    assert fx_result.missing == 1
    assert stock_result.inserted == 0
    assert stock_result.missing == 1


async def test_sync_fx_rates_defaults_usd_to_base_currency_when_empty(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.2: discovery has a USD/base default pair so empty databases are not skipped."""
    requested: list[tuple[str, str, date, date]] = []

    async def fake_fetch(
        base: str, quote: str, start_date: date, end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        requested.append((base, quote, start_date, end_date))
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.FxRateObservation(
                    base_currency=base,
                    quote_currency=quote,
                    rate=Decimal("1.350000"),
                    rate_date=requested_date,
                    source="test_primary",
                )
                for requested_date in market_data._iter_dates(start_date, end_date)
            ]
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", fake_fetch)

    result = await market_data.sync_fx_rates(
        db,
        pairs=await observed_fx_pairs(db, None),
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
    )

    assert requested == [("USD", "SGD", date(2026, 1, 5), date(2026, 1, 5))]
    assert result.inserted == 1


async def test_observed_fx_pairs_include_default_and_non_base_business_currency(
    db: AsyncSession,
    test_user,
) -> None:
    """AC11.10.2: Non-default currencies are discovered from business data."""
    db.add(
        Account(
            user_id=test_user.id,
            name="HKD Cash",
            type=AccountType.ASSET,
            currency="HKD",
        )
    )
    await db.commit()

    pairs = await observed_fx_pairs(db, test_user.id)

    assert pairs == ["HKD/SGD", "USD/SGD"]


async def test_active_stock_symbols_use_active_nonzero_holdings(
    db: AsyncSession,
    test_user,
) -> None:
    """AC11.10.1: Stock sync discovers active non-zero holdings by user."""
    account = Account(
        user_id=test_user.id,
        name="Brokerage",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(account)
    await db.flush()
    db.add_all(
        [
            ManagedPosition(
                user_id=test_user.id,
                account_id=account.id,
                asset_identifier="aapl",
                quantity=Decimal("2"),
                cost_basis=Decimal("100.00"),
                currency="USD",
                acquisition_date=date(2026, 1, 1),
                status=PositionStatus.ACTIVE,
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            ManagedPosition(
                user_id=test_user.id,
                account_id=account.id,
                asset_identifier="MSFT",
                quantity=Decimal("0"),
                cost_basis=Decimal("0.00"),
                currency="USD",
                acquisition_date=date(2026, 1, 1),
                status=PositionStatus.ACTIVE,
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            ManagedPosition(
                user_id=test_user.id,
                account_id=account.id,
                asset_identifier="TSLA",
                quantity=Decimal("1"),
                cost_basis=Decimal("100.00"),
                currency="USD",
                acquisition_date=date(2026, 1, 1),
                status=PositionStatus.DISPOSED,
                cost_basis_method=CostBasisMethod.FIFO,
            ),
        ]
    )
    await db.commit()

    assert await active_stock_symbols(db, test_user.id) == ["AAPL"]


async def test_sync_stock_prices_records_missing_trading_days(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.3: AC11.10.3: Missing provider days are counted without failing the sync."""

    async def fake_fetch(
        _symbol: str, _start_date: date, _end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(observations=[])

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_fetch)

    result = await market_data.sync_stock_prices(
        db,
        symbols=["MSFT"],
        start_date=date(2026, 1, 10),
        end_date=date(2026, 1, 10),
    )

    assert result.inserted == 0
    assert result.missing == 1
    assert result.disagreements == []


async def test_sync_stock_prices_skips_empty_symbols_and_completed_ranges(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.1: Stock sync skips blank symbols and completed incremental ranges."""
    db.add(
        StockPrice(
            symbol="AAPL",
            price=Decimal("150.000000"),
            currency="USD",
            price_date=date(2026, 1, 6),
            source="seed",
        )
    )
    await db.commit()

    async def fake_fetch(
        _symbol: str, _start_date: date, _end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        raise AssertionError("completed ranges should not call the provider")

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_fetch)

    result = await market_data.sync_stock_prices(
        db,
        symbols=["", "AAPL"],
        end_date=date(2026, 1, 5),
    )

    assert result.requested == 0
    assert result.inserted == 0


async def test_stock_provider_disagreement_is_reported_without_persisting(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.4: AC11.10.4: Provider disagreement is visible and not silently persisted."""

    async def fake_fetch(
        symbol: str, start_date: date, _end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            disagreements=[
                market_data.ProviderDisagreement(
                    asset=symbol,
                    observed_date=start_date,
                    primary_source="yahoo_finance",
                    secondary_source="stooq",
                    primary_value=Decimal("100.00"),
                    secondary_value=Decimal("112.00"),
                    relative_difference=Decimal("0.12"),
                    threshold=Decimal("0.02"),
                )
            ],
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_fetch)

    result = await market_data.sync_stock_prices(
        db,
        symbols=["MSFT"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
    )

    assert result.inserted == 0
    assert result.missing == 0
    assert len(result.disagreements) == 1
    assert result.disagreements[0].asset == "MSFT"
    count = await db.scalar(select(func.count()).select_from(StockPrice).where(StockPrice.symbol == "MSFT"))
    assert count == 0


async def test_portfolio_uses_synced_stock_price_before_atomic_snapshot(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-pricing.marketdata.6: AC11.10.6: Portfolio valuation prefers synced stock prices over stale snapshots."""
    account = Account(
        user_id=test_user.id,
        name="Brokerage",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="AAPL",
        quantity=Decimal("2"),
        cost_basis=Decimal("100.00"),
        currency="SGD",
        acquisition_date=date(2026, 1, 1),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    stale_snapshot = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date(2026, 1, 5),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("2"),
        market_value=Decimal("100.00"),
        currency="SGD",
        dedup_hash="aapl-stale-snapshot",
        source_documents={},
    )
    synced_price = StockPrice(
        symbol="AAPL",
        price=Decimal("155.000000"),
        currency="SGD",
        price_date=date(2026, 1, 6),
        source="test_sync",
    )
    db.add_all([position, stale_snapshot, synced_price])
    await db.commit()

    holdings = await PortfolioService().get_holdings(
        db,
        user_id=test_user.id,
        as_of_date=date(2026, 1, 6),
    )

    assert len(holdings) == 1
    assert holdings[0].market_value == Decimal("310.00")
    assert holdings[0].unrealized_pnl == Decimal("210.00")


async def test_portfolio_quantizes_synced_stock_market_values(
    db: AsyncSession,
    test_user,
) -> None:
    """AC11.10.6: Synced provider prices are rounded to money scale for holding responses."""
    account = Account(
        user_id=test_user.id,
        name="Brokerage",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="AAPL",
        quantity=Decimal("3"),
        cost_basis=Decimal("26.90"),
        currency="SGD",
        acquisition_date=date(2026, 1, 1),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    snapshot = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date(2026, 1, 5),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("3"),
        market_value=Decimal("300.00"),
        currency="SGD",
        dedup_hash="aapl-decimal-snapshot",
        source_documents={},
    )
    synced_price = StockPrice(
        symbol="AAPL",
        price=Decimal("173.980232"),
        currency="SGD",
        price_date=date(2026, 1, 6),
        source="test_sync",
    )
    db.add_all([position, snapshot, synced_price])
    await db.commit()

    holdings = await PortfolioService().get_holdings(
        db,
        user_id=test_user.id,
        as_of_date=date(2026, 1, 6),
    )

    assert holdings[0].market_value == Decimal("521.94")
    assert holdings[0].unrealized_pnl == Decimal("495.04")


async def test_persist_stock_price_returns_existing_row(
    db: AsyncSession,
) -> None:
    """AC11.10.1: Persisting a duplicate stock price returns the existing row idempotently."""
    db.add(
        StockPrice(
            symbol="AAPL",
            price=Decimal("150.000000"),
            currency="USD",
            price_date=date(2026, 1, 5),
            source="seed",
        )
    )
    await db.commit()

    price = await market_data._persist_stock_price(
        db,
        market_data.StockPriceObservation(
            symbol="aapl",
            price=Decimal("160.000000"),
            currency="USD",
            price_date=date(2026, 1, 5),
            source="new",
        ),
    )

    assert price == Decimal("150.000000")


async def test_persist_stock_price_reraises_integrity_error_without_concurrent_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.1: Stock price persistence reraises unresolved concurrent insert errors."""

    class NestedTransaction:
        async def __aenter__(self) -> "NestedTransaction":
            return self

        async def __aexit__(self, *_exc_info: object) -> bool:
            return False

    class FakeDb:
        def add(self, _row: object) -> None:
            return None

        async def flush(self) -> None:
            raise IntegrityError("insert", {}, Exception("duplicate"))

        async def rollback(self) -> None:
            return None

        def begin_nested(self) -> NestedTransaction:
            return NestedTransaction()

    async def fake_load(*_args: object) -> None:
        return None

    monkeypatch.setattr(market_data._store, "_load_stored_stock_price_on_date", fake_load)

    with pytest.raises(IntegrityError):
        await market_data._persist_stock_price(
            FakeDb(),  # type: ignore[arg-type]
            market_data.StockPriceObservation(
                symbol="AAPL",
                price=Decimal("160.000000"),
                currency="USD",
                price_date=date(2026, 1, 5),
                source="new",
            ),
        )


async def test_upsert_sync_state_handles_concurrent_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.9: Sync state upsert resolves concurrent inserts idempotently."""

    class NestedTransaction:
        async def __aenter__(self) -> "NestedTransaction":
            return self

        async def __aexit__(self, *_exc_info: object) -> bool:
            return False

    class FakeState:
        last_success_at = datetime(2026, 1, 4, tzinfo=UTC)
        last_success_date = date(2026, 1, 4)
        last_observation_date = date(2026, 1, 4)
        updated_at = datetime(2026, 1, 4, tzinfo=UTC)

    class FakeDb:
        flushes = 0

        def add(self, _row: object) -> None:
            return None

        async def flush(self) -> None:
            self.flushes += 1
            if self.flushes == 1:
                raise IntegrityError("insert", {}, Exception("duplicate"))

        async def rollback(self) -> None:
            return None

        def begin_nested(self) -> NestedTransaction:
            return NestedTransaction()

    calls = 0
    state = FakeState()

    async def fake_load(_db: object, _kind: str, _scope: str) -> FakeState | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else state

    monkeypatch.setattr(market_data._store, "_load_sync_state", fake_load)

    observed_now = datetime(2026, 1, 6, tzinfo=UTC)
    db = FakeDb()
    await market_data._upsert_sync_state(
        db,  # type: ignore[arg-type]
        kind="stock",
        scope="AAPL",
        last_success_date=date(2026, 1, 6),
        last_observation_date=date(2026, 1, 5),
        now=observed_now,
    )

    assert db.flushes == 2
    assert state.last_success_at == observed_now
    assert state.last_success_date == date(2026, 1, 6)


async def test_market_data_freshness_sync_runs_once_after_24h(
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.9: AC11.10.9: Report freshness checks trigger one immediate sync after 24h."""
    account = Account(
        user_id=test_user.id,
        name="USD Brokerage",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(account)
    await db.flush()
    db.add(
        ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("1"),
            cost_basis=Decimal("100.00"),
            currency="USD",
            acquisition_date=date(2026, 1, 1),
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    stale_success = datetime(2026, 1, 4, 0, 0, tzinfo=UTC)
    db.add_all(
        [
            MarketDataSyncState(
                kind="fx",
                scope="USD/SGD",
                last_success_at=stale_success,
                last_success_date=date(2026, 1, 4),
                last_observation_date=date(2026, 1, 4),
                created_at=stale_success,
                updated_at=stale_success,
            ),
            MarketDataSyncState(
                kind="stock",
                scope="AAPL",
                last_success_at=stale_success,
                last_success_date=date(2026, 1, 4),
                last_observation_date=date(2026, 1, 4),
                created_at=stale_success,
                updated_at=stale_success,
            ),
        ]
    )
    await db.commit()

    async def fake_fx_fetch(
        base: str, quote: str, start_date: date, end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.FxRateObservation(
                    base_currency=base,
                    quote_currency=quote,
                    rate=Decimal("1.350000"),
                    rate_date=requested_date,
                    source="test_primary",
                )
                for requested_date in market_data._iter_dates(start_date, end_date)
            ]
        )

    async def fake_stock_fetch(
        symbol: str, start_date: date, end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.StockPriceObservation(
                    symbol=symbol,
                    price=Decimal("200.000000"),
                    currency="USD",
                    price_date=requested_date,
                    source="test_primary",
                )
                for requested_date in market_data._iter_dates(start_date, end_date)
            ]
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", fake_fx_fetch)
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_stock_fetch)

    checked_at = datetime(2026, 1, 6, 8, 0, tzinfo=UTC)
    fx_pairs = await observed_fx_pairs(db, test_user.id)
    stock_symbols = await active_stock_symbols(db, test_user.id)
    first = await market_data.ensure_market_data_fresh(
        db,
        fx_pairs=fx_pairs,
        stock_symbols=stock_symbols,
        end_date=date(2026, 1, 6),
        now=checked_at,
    )
    second = await market_data.ensure_market_data_fresh(
        db,
        fx_pairs=fx_pairs,
        stock_symbols=stock_symbols,
        end_date=date(2026, 1, 6),
        now=checked_at + timedelta(hours=1),
    )

    assert first.triggered is True
    assert first.fx.requested > 0
    assert first.stock.requested > 0
    assert second.triggered is False


async def test_market_data_freshness_backfills_report_date_when_latest_price_is_newer(
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.9: Fresh sync state does not skip a missing historical report-date price."""
    account = Account(
        user_id=test_user.id,
        name="Historical Brokerage",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    db.add_all(
        [
            ManagedPosition(
                user_id=test_user.id,
                account_id=account.id,
                asset_identifier="IBM",
                quantity=Decimal("1"),
                cost_basis=Decimal("100.00"),
                currency="SGD",
                acquisition_date=date(2024, 1, 1),
                status=PositionStatus.ACTIVE,
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            StockPrice(
                symbol="IBM",
                price=Decimal("200.000000"),
                currency="USD",
                price_date=date(2026, 1, 6),
                source="future_seed",
            ),
            MarketDataSyncState(
                kind="stock",
                scope="IBM",
                last_success_at=datetime(2026, 1, 6, 8, 0, tzinfo=UTC),
                last_success_date=date(2026, 1, 6),
                last_observation_date=date(2026, 1, 6),
                created_at=datetime(2026, 1, 6, 8, 0, tzinfo=UTC),
                updated_at=datetime(2026, 1, 6, 8, 0, tzinfo=UTC),
            ),
        ]
    )
    await db.commit()

    requested_ranges: list[tuple[str, date, date]] = []

    async def fake_stock_fetch(
        symbol: str, start_date: date, end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        requested_ranges.append((symbol, start_date, end_date))
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.StockPriceObservation(
                    symbol=symbol,
                    price=Decimal("150.000000"),
                    currency="USD",
                    price_date=end_date,
                    source="test_primary",
                )
            ]
        )

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_stock_fetch)

    result = await market_data.ensure_market_data_fresh(
        db,
        fx_pairs=await observed_fx_pairs(db, test_user.id),
        stock_symbols=await active_stock_symbols(db, test_user.id),
        end_date=date(2024, 6, 3),
        now=datetime(2026, 1, 6, 9, 0, tzinfo=UTC),
    )

    assert result.triggered is True
    assert requested_ranges == [("IBM", date(2024, 5, 28), date(2024, 6, 3))]
    assert result.stock.inserted == 1


async def test_market_data_freshness_skips_same_currency_pair(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.9: Report freshness ignores same-currency FX scopes."""

    async def fake_sync(*_args: object, **_kwargs: object) -> market_data.MarketDataSyncResult:
        raise AssertionError("same-currency scope should not sync")

    monkeypatch.setattr(market_data.service, "sync_fx_rates", fake_sync)

    result = await market_data.ensure_market_data_fresh(
        db,
        fx_pairs=["SGD/SGD"],
        stock_symbols=[],
        end_date=date(2026, 1, 5),
    )

    assert result.triggered is False


async def test_market_data_sync_state_updates_when_provider_has_no_rows(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.9: A successful no-row provider sync refreshes state to avoid repeated report calls."""

    async def fake_fetch(
        _symbol: str, _start_date: date, _end_date: date
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(observations=[], provider_success=True)

    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", fake_fetch)

    result = await market_data.sync_stock_prices(
        db,
        symbols=["AAPL"],
        start_date=date(2026, 1, 10),
        end_date=date(2026, 1, 11),
    )

    assert result.inserted == 0
    assert result.missing == 2
    state = await db.scalar(
        select(MarketDataSyncState)
        .where(MarketDataSyncState.kind == "stock")
        .where(MarketDataSyncState.scope == "AAPL")
    )
    assert state is not None
    assert state.last_success_date == date(2026, 1, 11)


async def test_market_data_status_requires_observation_date_for_freshness(
    db: AsyncSession,
) -> None:
    """AC11.10.11: Freshness status requires data evidence, not only a recent provider call."""
    observed_at = datetime(2026, 1, 11, tzinfo=UTC)
    db.add(
        MarketDataSyncState(
            kind="stock",
            scope="AAPL",
            last_success_at=observed_at,
            last_success_date=date(2026, 1, 11),
            last_observation_date=None,
            created_at=observed_at,
            updated_at=observed_at,
        )
    )
    await db.commit()

    status = await market_data.get_market_data_status(
        db,
        pairs=[],
        symbols=["AAPL"],
        now=datetime(2026, 1, 11, 1, 0, tzinfo=UTC),
    )

    assert len(status) == 1
    assert status[0].fresh is False
    assert status[0].last_observation_date is None


async def test_market_data_status_falls_back_to_persisted_observation_date(
    db: AsyncSession,
) -> None:
    """AC11.10.11: Status backfills older sync states from persisted price evidence."""
    observed_at = datetime(2026, 1, 11, tzinfo=UTC)
    db.add_all(
        [
            StockPrice(
                symbol="AAPL",
                price=Decimal("190.000000"),
                currency="USD",
                price_date=date(2026, 1, 10),
                source="test",
            ),
            MarketDataSyncState(
                kind="stock",
                scope="AAPL",
                last_success_at=observed_at,
                last_success_date=date(2026, 1, 11),
                last_observation_date=None,
                created_at=observed_at,
                updated_at=observed_at,
            ),
        ]
    )
    await db.commit()

    status = await market_data.get_market_data_status(
        db,
        pairs=[],
        symbols=["AAPL"],
        now=datetime(2026, 1, 11, 1, 0, tzinfo=UTC),
    )

    assert len(status) == 1
    assert status[0].fresh is True
    assert status[0].last_observation_date == date(2026, 1, 10)
