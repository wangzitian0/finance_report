"""Tests for FX rate service."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from common.testing.ac_proof import ac_proof
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import ExchangeRate, Money
from src.config import settings
from src.pricing.extension import market_data
from src.pricing.orm.market_data import FxRate
from src.services import fx as fx_service
from src.services.fx import (
    FxRateError,
    convert_amount,
    convert_to_base,
    get_average_rate,
    get_exchange_rate,
)


@pytest.fixture(autouse=True)
def clear_fx_cache() -> None:
    """Clear FX cache to avoid cross-test contamination."""
    fx_service._cache._store.clear()


async def test_get_exchange_rate_exact(db: AsyncSession):
    """Exact FX rate lookup should return stored rate."""
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.350000"),
        rate_date=date(2025, 1, 1),
        source="test",
    )
    db.add(rate)
    await db.commit()

    result = await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 1))

    assert result == Decimal("1.350000")


async def test_get_exchange_rate_fallback(db: AsyncSession):
    """FX rate lookup should fall back to most recent prior rate."""
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.320000"),
        rate_date=date(2025, 1, 1),
        source="test",
    )
    db.add(rate)
    await db.commit()

    result = await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 3))

    assert result == Decimal("1.320000")


async def test_get_exchange_rate_lazy_derives_inverse(db: AsyncSession):
    """[AC5.4.3] Lazy FX lookup should derive and persist inverse rates."""
    db.add(
        FxRate(
            base_currency="SGD",
            quote_currency="HKD",
            rate=Decimal("5.800000"),
            rate_date=date(2025, 6, 30),
            source="test",
        )
    )
    await db.commit()

    result = await get_exchange_rate(db, "HKD", "SGD", date(2025, 6, 30), lazy_load=True)

    assert result == Decimal("0.172414")
    persisted = await db.execute(
        select(FxRate).where(
            FxRate.base_currency == "HKD",
            FxRate.quote_currency == "SGD",
            FxRate.rate_date == date(2025, 6, 30),
        )
    )
    derived = persisted.scalar_one()
    assert derived.rate == Decimal("0.172414")
    assert derived.source == "derived:inverse:SGD/HKD"


async def test_get_exchange_rate_lazy_fetches_provider_when_enabled(db: AsyncSession, monkeypatch):
    """[AC5.4.3] Lazy FX lookup should persist provider rates when DB derivation is unavailable."""

    async def fake_yahoo_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation:
        assert (base, quote, requested_date) == ("HKD", "SGD", date(2025, 6, 30))
        return market_data.FxRateObservation(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("0.173077"),
            rate_date=requested_date,
            source="yahoo_finance",
        )

    monkeypatch.setattr(settings, "market_data_lazy_fetch_enabled", True)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", fake_yahoo_fetch)

    result = await get_exchange_rate(db, "HKD", "SGD", date(2025, 6, 30), lazy_load=True)

    assert result == Decimal("0.173077")
    persisted = await db.execute(
        select(FxRate).where(
            FxRate.base_currency == "HKD",
            FxRate.quote_currency == "SGD",
            FxRate.rate_date == date(2025, 6, 30),
        )
    )
    provider_rate = persisted.scalar_one()
    assert provider_rate.rate == Decimal("0.173077")
    assert provider_rate.source == "yahoo_finance"


async def test_resolve_missing_fx_rate_same_currency_returns_identity(db: AsyncSession):
    """[AC5.4.3] Lazy FX resolution should return identity for same-currency pairs."""
    result = await market_data.resolve_missing_fx_rate(db, "sgd", "SGD", date(2025, 6, 30))

    assert result == Decimal("1")


async def test_resolve_missing_fx_rate_returns_stored_direct_rate(db: AsyncSession):
    """[AC5.4.3] Lazy FX resolution should use an existing direct DB rate without persisting."""
    db.add(
        FxRate(
            base_currency="HKD",
            quote_currency="SGD",
            rate=Decimal("0.173000"),
            rate_date=date(2025, 6, 29),
            source="test",
        )
    )
    await db.commit()

    result = await market_data.resolve_missing_fx_rate(db, "hkd", "sgd", date(2025, 6, 30))

    assert result == Decimal("0.173000")


async def test_resolve_missing_fx_rate_returns_none_when_provider_misses(db: AsyncSession, monkeypatch):
    """[AC5.4.3] Lazy FX resolution should return None when derivation and provider fetch miss."""

    async def fake_provider_fetch(_base: str, _quote: str, _requested_date: date) -> None:
        return None

    monkeypatch.setattr(settings, "market_data_lazy_fetch_enabled", True)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_or_derived_fx_rate", fake_provider_fetch)

    result = await market_data.resolve_missing_fx_rate(db, "HKD", "SGD", date(2025, 6, 30))

    assert result is None


async def test_persist_fx_rate_keeps_existing_same_day_rate(db: AsyncSession):
    """[AC5.4.3] Lazy FX persistence should not overwrite an existing same-day rate."""
    db.add(
        FxRate(
            base_currency="HKD",
            quote_currency="SGD",
            rate=Decimal("0.173000"),
            rate_date=date(2025, 6, 30),
            source="manual",
        )
    )
    await db.commit()

    result = await market_data._persist_fx_rate(
        db,
        market_data.FxRateObservation(
            base_currency="hkd",
            quote_currency="sgd",
            rate=Decimal("0.180000"),
            rate_date=date(2025, 6, 30),
            source="yahoo_finance",
        ),
    )

    assert result == Decimal("0.173000")
    persisted = await db.execute(select(FxRate).where(FxRate.base_currency == "HKD", FxRate.quote_currency == "SGD"))
    rate = persisted.scalar_one()
    assert rate.rate == Decimal("0.173000")
    assert rate.source == "manual"


async def test_persist_fx_rate_handles_concurrent_insert():
    """[AC5.4.3] Lazy FX persistence should return the concurrent same-day insert after IntegrityError."""

    class Row:
        rate = Decimal("0.173500")
        rate_date = date(2025, 6, 30)
        source = "concurrent"

    class Result:
        def __init__(self, row):
            self._row = row

        def one_or_none(self):
            return self._row

    class NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return False

    class FakeSession:
        def __init__(self):
            self.execute_calls = 0
            self.rolled_back = False
            self.added = None

        async def execute(self, _stmt):
            self.execute_calls += 1
            return Result(None if self.execute_calls == 1 else Row())

        def add(self, value):
            self.added = value

        async def flush(self):
            raise IntegrityError("insert fx", {}, Exception("duplicate"))

        async def rollback(self):
            self.rolled_back = True

        def begin_nested(self):
            return NestedTransaction()

    session = FakeSession()

    result = await market_data._persist_fx_rate(
        session,
        market_data.FxRateObservation(
            base_currency="HKD",
            quote_currency="SGD",
            rate=Decimal("0.173077"),
            rate_date=date(2025, 6, 30),
            source="yahoo_finance",
        ),
    )

    assert result == Decimal("0.173500")
    assert session.rolled_back is False
    assert session.added is not None


async def test_persist_fx_rate_reraises_integrity_error_without_concurrent_rate():
    """[AC5.4.3] Lazy FX persistence should re-raise an unexpected IntegrityError."""

    class Result:
        def one_or_none(self):
            return None

    class NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return False

    class FakeSession:
        async def execute(self, _stmt):
            return Result()

        def add(self, _value):
            return None

        async def flush(self):
            raise IntegrityError("insert fx", {}, Exception("duplicate"))

        async def rollback(self):
            return None

        def begin_nested(self):
            return NestedTransaction()

    with pytest.raises(IntegrityError):
        await market_data._persist_fx_rate(
            FakeSession(),
            market_data.FxRateObservation(
                base_currency="HKD",
                quote_currency="SGD",
                rate=Decimal("0.173077"),
                rate_date=date(2025, 6, 30),
                source="yahoo_finance",
            ),
        )


async def test_fetch_yahoo_or_derived_fx_rate_uses_inverse(monkeypatch):
    """[AC5.4.3] Yahoo lazy fetch should derive inverse provider rates."""

    async def fake_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation | None:
        if (base, quote, requested_date) == ("SGD", "HKD", date(2025, 6, 30)):
            return market_data.FxRateObservation(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("5.800000"),
                rate_date=requested_date,
                source="yahoo_finance",
            )
        return None

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", fake_fetch)

    result = await market_data._fetch_yahoo_or_derived_fx_rate("HKD", "SGD", date(2025, 6, 30))

    assert result == market_data.FxRateObservation(
        base_currency="HKD",
        quote_currency="SGD",
        rate=Decimal("0.172414"),
        rate_date=date(2025, 6, 30),
        source="yahoo_finance:inverse",
    )


async def test_fetch_yahoo_or_derived_fx_rate_uses_bridge(monkeypatch):
    """[AC5.4.3] Yahoo lazy fetch should derive bridge-provider rates."""

    async def fake_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation | None:
        observations = {
            ("HKD", "USD"): market_data.FxRateObservation(
                base_currency="HKD",
                quote_currency="USD",
                rate=Decimal("0.128205"),
                rate_date=date(2025, 6, 29),
                source="yahoo_finance",
            ),
            ("USD", "SGD"): market_data.FxRateObservation(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=date(2025, 6, 30),
                source="yahoo_finance",
            ),
        }
        assert requested_date == date(2025, 6, 30)
        return observations.get((base, quote))

    monkeypatch.setattr(settings, "market_data_fx_bridge_currency", "USD")
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", fake_fetch)

    result = await market_data._fetch_yahoo_or_derived_fx_rate("HKD", "SGD", date(2025, 6, 30))

    assert result == market_data.FxRateObservation(
        base_currency="HKD",
        quote_currency="SGD",
        rate=Decimal("0.173077"),
        rate_date=date(2025, 6, 30),
        source="yahoo_finance:bridge:USD",
    )


async def test_fetch_yahoo_or_derived_fx_rate_skips_bridge_when_bridge_is_pair_currency(monkeypatch):
    """[AC5.4.3] Yahoo lazy fetch should not bridge through the requested pair currencies."""

    async def fake_fetch(_base: str, _quote: str, _requested_date: date) -> None:
        return None

    monkeypatch.setattr(settings, "market_data_fx_bridge_currency", "SGD")
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", fake_fetch)

    result = await market_data._fetch_yahoo_or_derived_fx_rate("HKD", "SGD", date(2025, 6, 30))

    assert result is None


async def test_fetch_yahoo_or_derived_fx_rate_returns_none_when_bridge_leg_missing(monkeypatch):
    """[AC5.4.3] Yahoo lazy fetch should return None when a bridge leg is unavailable."""

    async def fake_fetch(base: str, quote: str, _requested_date: date) -> market_data.FxRateObservation | None:
        if (base, quote) == ("HKD", "USD"):
            return market_data.FxRateObservation(
                base_currency="HKD",
                quote_currency="USD",
                rate=Decimal("0.128205"),
                rate_date=date(2025, 6, 30),
                source="yahoo_finance",
            )
        return None

    monkeypatch.setattr(settings, "market_data_fx_bridge_currency", "USD")
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", fake_fetch)

    result = await market_data._fetch_yahoo_or_derived_fx_rate("HKD", "SGD", date(2025, 6, 30))

    assert result is None


async def test_fetch_yahoo_fx_rate_success(monkeypatch):
    """[AC5.4.3] Yahoo FX fetch should request a bounded daily chart window and parse a rate."""
    calls = []
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [market_data._date_to_epoch(date(2025, 6, 29))],
                    "indicators": {"quote": [{"close": [0.173077]}]},
                }
            ]
        }
    }

    class FakeClient:
        def __init__(self, *, timeout, headers):
            self.timeout = timeout
            self.headers = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

        async def get(self, url, params):
            calls.append((self.timeout, self.headers, url, params))
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(market_data.httpx, "AsyncClient", FakeClient)

    result = await market_data._fetch_yahoo_fx_rate("HKD", "SGD", date(2025, 6, 30))

    assert result == market_data.FxRateObservation(
        base_currency="HKD",
        quote_currency="SGD",
        rate=Decimal("0.173077"),
        rate_date=date(2025, 6, 29),
        source="yahoo_finance",
    )
    timeout, headers, url, params = calls[0]
    assert timeout == settings.market_data_yahoo_timeout_seconds
    assert headers["User-Agent"] == "finance-report-audit/1.0"
    assert url == "https://query1.finance.yahoo.com/v8/finance/chart/HKDSGD=X"
    assert params["interval"] == "1d"


async def test_fetch_yahoo_fx_rate_returns_none_on_http_error(monkeypatch):
    """[AC5.4.3] Yahoo FX fetch should convert HTTP errors into cache misses."""

    class FailingClient:
        def __init__(self, *, timeout, headers):
            self.timeout = timeout
            self.headers = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

        async def get(self, url, params):
            raise httpx.ConnectError("offline", request=httpx.Request("GET", url))

    monkeypatch.setattr(market_data.httpx, "AsyncClient", FailingClient)

    result = await market_data._fetch_yahoo_fx_rate("HKD", "SGD", date(2025, 6, 30))

    assert result is None


def test_parse_yahoo_fx_response_selects_latest_on_or_before_requested_date():
    """[AC5.4.3] Yahoo parser should ignore null and future closes and select the latest eligible close."""
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [
                        market_data._date_to_epoch(date(2025, 6, 28)),
                        market_data._date_to_epoch(date(2025, 6, 29)),
                        market_data._date_to_epoch(date(2025, 7, 1)),
                    ],
                    "indicators": {"quote": [{"close": [None, 0.1730774, 0.200000]}]},
                }
            ]
        }
    }

    rows = market_data._parse_yahoo_fx_response_series(payload, "HKD", "SGD", date.min, date(2025, 6, 30))
    result = max(rows, key=lambda item: item.rate_date, default=None)

    assert result == market_data.FxRateObservation(
        base_currency="HKD",
        quote_currency="SGD",
        rate=Decimal("0.173077"),
        rate_date=date(2025, 6, 29),
        source="yahoo_finance",
    )


def test_parse_yahoo_fx_response_returns_none_for_empty_or_unusable_payloads():
    """[AC5.4.3] Yahoo parser should return None when the payload has no usable close."""
    assert market_data._parse_yahoo_fx_response_series({}, "HKD", "SGD", date.min, date(2025, 6, 30)) == []
    assert (
        market_data._parse_yahoo_fx_response_series(
            {
                "chart": {
                    "result": [
                        {
                            "timestamp": [market_data._date_to_epoch(date(2025, 7, 1))],
                            "indicators": {"quote": [{"close": [0.200000]}]},
                        }
                    ]
                }
            },
            "HKD",
            "SGD",
            date.min,
            date(2025, 6, 30),
        )
        == []
    )


async def test_get_average_rate(db: AsyncSession):
    """Average rate should be computed for the period."""
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.300000"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.500000"),
                rate_date=date(2025, 1, 2),
                source="test",
            ),
        ]
    )
    await db.commit()

    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 2))

    assert result == Decimal("1.400000")


async def test_convert_amount(db: AsyncSession):
    """Convert amount should apply the stored FX rate."""
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.200000"),
        rate_date=date(2025, 1, 1),
        source="test",
    )
    db.add(rate)
    await db.commit()

    amount = Decimal("100.00")
    expected = amount * Decimal("1.200000")

    result = await convert_amount(db, amount, "USD", "SGD", date(2025, 1, 1))

    assert result == expected


@ac_proof(
    proof_id="test_fx_convert_amount_uses_typed_money_exchange_rate",
    ac_ids=["AC-audit.31.2"],
    ci_tier="pr_ci",
)
async def test_AC12_31_2_convert_amount_routes_through_money_exchange_rate(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """AC-audit.31.2: service boundary wraps storage Decimal in Money + ExchangeRate."""
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.200000"),
        rate_date=date(2025, 1, 1),
        source="test",
    )
    db.add(rate)
    await db.commit()

    calls: list[tuple[Money, ExchangeRate]] = []

    def fake_convert(money: Money, rate: ExchangeRate) -> Money:
        calls.append((money, rate))
        return Money(Decimal("120.00"), "SGD")

    # ``convert_money`` is now the public Money-native FX helper; the common
    # money primitive is imported privately as ``_money_convert`` (what
    # convert_amount routes through).
    monkeypatch.setattr(fx_service, "_money_convert", fake_convert)

    result = await convert_amount(db, Decimal("100.00"), "USD", "SGD", date(2025, 1, 1))

    assert result == Decimal("120.00")
    assert len(calls) == 1
    money, typed_rate = calls[0]
    assert money == Money(Decimal("100.00"), "USD")
    assert typed_rate == ExchangeRate("USD", "SGD", Decimal("1.200000"))


@pytest.mark.no_db
async def test_convert_amount_wraps_invalid_currency_as_fx_rate_error(monkeypatch: pytest.MonkeyPatch):
    """Legacy/provider rate rows with non-ISO codes should not leak Money errors."""

    async def fake_get_exchange_rate(*args, **kwargs) -> Decimal:
        return Decimal("60000.000000")

    monkeypatch.setattr(fx_service, "get_exchange_rate", fake_get_exchange_rate)

    with pytest.raises(FxRateError, match="Invalid FX conversion boundary"):
        await convert_amount(None, Decimal("0.50"), "BTC", "USD", date(2025, 1, 1))  # type: ignore[arg-type]


async def test_get_exchange_rate_same_currency(db: AsyncSession):
    result = await get_exchange_rate(db, "usd", "USD", date(2025, 1, 1))
    assert result == Decimal("1")


async def test_get_exchange_rate_missing_raises(db: AsyncSession):
    with pytest.raises(FxRateError, match="No FX rate available"):
        await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 1))


async def test_get_average_rate_invalid_range(db: AsyncSession):
    with pytest.raises(FxRateError, match="start_date must be before end_date"):
        await get_average_rate(db, "USD", "SGD", date(2025, 1, 2), date(2025, 1, 1))


async def test_get_average_rate_falls_back_to_exchange_rate(db: AsyncSession):
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.250000"),
            rate_date=date(2025, 1, 3),
            source="test",
        )
    )
    await db.commit()

    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 3))

    assert result == Decimal("1.250000")


async def test_convert_amount_uses_average_rate(db: AsyncSession):
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.200000"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.400000"),
                rate_date=date(2025, 1, 2),
                source="test",
            ),
        ]
    )
    await db.commit()

    result = await convert_amount(
        db,
        Decimal("10.00"),
        "USD",
        "SGD",
        date(2025, 1, 2),
        average_start=date(2025, 1, 1),
        average_end=date(2025, 1, 2),
    )

    assert result == Decimal("13.00")


async def test_convert_amount_same_currency(db: AsyncSession):
    result = await convert_amount(
        db,
        Decimal("10.00"),
        "SGD",
        "sgd",
        date(2025, 1, 1),
    )

    assert result == Decimal("10.00")


async def test_convert_to_base(db: AsyncSession):
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.300000"),
            rate_date=date(2025, 1, 1),
            source="test",
        )
    )
    await db.commit()

    result = await convert_to_base(db, Decimal("10.00"), "USD", date(2025, 1, 1))

    assert result == Decimal("13.000000")


def test_fx_cache_expired_entry() -> None:
    expired = fx_service._CacheEntry(
        value=Decimal("1.23"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    fx_service._cache._store["expired"] = expired
    assert fx_service._cache.get("expired") is None


def test_fx_cache_hit() -> None:
    entry = fx_service._CacheEntry(
        value=Decimal("1.10"),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    fx_service._cache._store["hit"] = entry
    assert fx_service._cache.get("hit") == Decimal("1.10")


async def test_get_exchange_rate_uses_cache(db: AsyncSession):
    key = "fx:USD:SGD:2025-01-01"
    fx_service._cache._store[key] = fx_service._CacheEntry(
        value=Decimal("1.11"),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    result = await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 1))
    assert result == Decimal("1.11")


async def test_get_average_rate_uses_cache(db: AsyncSession):
    key = "fx:USD:SGD:2025-01-01:2025-01-02"
    fx_service._cache._store[key] = fx_service._CacheEntry(
        value=Decimal("1.22"),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 2))
    assert result == Decimal("1.22")


async def test_get_average_rate_same_currency(db: AsyncSession):
    result = await get_average_rate(db, "SGD", "SGD", date(2025, 1, 1), date(2025, 1, 2))
    assert result == Decimal("1")


async def test_get_exchange_rate_casts_non_decimal():
    class DummyResult:
        def scalar_one_or_none(self):
            return 1.2345

    class DummySession:
        async def execute(self, _stmt):
            return DummyResult()

    result = await get_exchange_rate(DummySession(), "USD", "SGD", date(2025, 1, 1))
    assert result == Decimal("1.2345")


async def test_get_average_rate_casts_non_decimal():
    class DummyResult:
        def scalar_one_or_none(self):
            return 1.11

    class DummySession:
        async def execute(self, _stmt):
            return DummyResult()

    result = await get_average_rate(DummySession(), "USD", "SGD", date(2025, 1, 1), date(2025, 1, 2))
    assert result == Decimal("1.11")


def test_fx_cache_eviction() -> None:
    """Test FX cache eviction logic when it reaches max_size."""
    # Create cache with small max_size for testing
    small_cache = fx_service._FxRateCache(max_size=5)

    # Fill cache
    for i in range(5):
        small_cache.set(f"key{i}", Decimal(str(i)))

    assert len(small_cache._store) == 5

    # Exceed capacity - should trigger eviction
    # Our implementation clears 20% + any expired.
    # Since none are expired, it will remove floor(5 * 0.2) = 1 entry (oldest).
    small_cache.set("key5", Decimal("5"))

    # After set, size should be 5 again (added 1, evicted 1)
    assert len(small_cache._store) == 5
    assert "key0" not in small_cache._store
    assert "key5" in small_cache._store


async def test_prefetched_fx_rates() -> None:
    """Test the PrefetchedFxRates helper class."""
    from src.services.fx import PrefetchedFxRates

    prefetched = PrefetchedFxRates()

    # Test set/get spot
    prefetched.set_rate("USD", "SGD", date(2025, 1, 1), Decimal("1.35"))
    assert prefetched.get_rate("USD", "SGD", date(2025, 1, 1)) == Decimal("1.35")

    # Test same currency
    assert prefetched.get_rate("SGD", "sgd", date(2025, 1, 1)) == Decimal("1")

    # Test avg rate
    prefetched.set_rate("USD", "SGD", date(2025, 1, 1), Decimal("1.34"), date(2025, 1, 1), date(2025, 1, 31))
    assert prefetched.get_rate("USD", "SGD", date(2025, 1, 1), date(2025, 1, 1), date(2025, 1, 31)) == Decimal("1.34")

    # Missing key
    assert prefetched.get_rate("GBP", "USD", date(2025, 1, 1)) is None


async def test_prefetch_parallel(db: AsyncSession):
    """Test batch prefetching from database."""
    from src.services.fx import PrefetchedFxRates

    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="EUR",
                quote_currency="SGD",
                rate=Decimal("1.40"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
        ]
    )
    await db.commit()

    prefetched = PrefetchedFxRates()
    # Fetch sequentially in test to avoid AsyncSession concurrency error
    # but still verifying the data structures and loading logic.
    await prefetched.prefetch(db, [("USD", "SGD", date(2025, 1, 1), None, None)])
    await prefetched.prefetch(db, [("EUR", "SGD", date(2025, 1, 1), None, None)])

    assert prefetched.get_rate("USD", "SGD", date(2025, 1, 1)) == Decimal("1.30")
    assert prefetched.get_rate("EUR", "SGD", date(2025, 1, 1)) == Decimal("1.40")


async def test_convert_amount_average_fallback_error(db: AsyncSession):
    """Test that convert_amount fails if fallback exchange rate lookup fails."""
    # No rates in DB
    with pytest.raises(FxRateError, match="No FX rate available"):
        await convert_amount(
            db,
            Decimal("10"),
            "USD",
            "SGD",
            date(2025, 1, 1),
            average_start=date(2025, 1, 1),
            average_end=date(2025, 1, 1),
        )
