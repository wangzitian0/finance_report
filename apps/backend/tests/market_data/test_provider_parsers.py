"""AC11.10: Market data provider parsing and validation tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from src.services import market_data


def _epoch(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def test_market_data_helper_boundaries() -> None:
    """AC11.10.2: Helper boundaries keep sync ranges and provider symbols deterministic."""
    assert market_data._iter_dates(date(2026, 1, 3), date(2026, 1, 1)) == []
    assert market_data._parse_fx_pair(" usd / sgd ") == ("USD", "SGD")
    with pytest.raises(ValueError, match="expected BASE/QUOTE"):
        market_data._parse_fx_pair("USD-SGD")

    assert market_data._default_start_date(date(2026, 1, 8)) == date(2026, 1, 2)
    assert market_data._incremental_start(date(2026, 1, 3), None, date(2026, 1, 5)) == date(2026, 1, 4)
    assert market_data._incremental_start(date(2026, 1, 6), None, date(2026, 1, 5)) is None
    assert market_data._relative_difference(Decimal("0"), Decimal("0")) == Decimal("0")
    assert market_data._relative_difference(Decimal("100"), Decimal("98")) == Decimal("0.020000")
    assert market_data._stooq_stock_symbol("AAPL") == "aapl.us"
    assert market_data._stooq_stock_symbol("0700.HK") == "0700.hk"
    assert market_data._stooq_fx_symbol("USD", "SGD") == "usdsgd"
    assert market_data._normalize_utc(datetime(2026, 1, 5)).tzinfo == UTC


def test_AC17_33_1_yahoo_stock_symbol_maps_hk_numeric_codes() -> None:
    """AC17.33.1: HK numeric exchange codes map to the Yahoo `<4-digit>.HK` symbol.

    Brokerages store Hong Kong equities by their numeric board-lot code (e.g.
    Xiaomi "01810"). Sent verbatim, Yahoo 404s; it expects "1810.HK". US
    alphabetic tickers and already-suffixed symbols must pass through unchanged.
    """
    assert market_data._yahoo_stock_symbol("01810") == "1810.HK"
    assert market_data._yahoo_stock_symbol("00700") == "0700.HK"
    assert market_data._yahoo_stock_symbol("700") == "0700.HK"
    assert market_data._yahoo_stock_symbol("AAPL") == "AAPL"
    assert market_data._yahoo_stock_symbol("brk.b") == "BRK.B"
    assert market_data._yahoo_stock_symbol("1810.HK") == "1810.HK"
    # CR on #1453: a 5-digit HKEX code is preserved (not truncated to 4)...
    assert market_data._yahoo_stock_symbol("10000") == "10000.HK"
    assert market_data._hk_numeric_code("10000") == "10000"
    # ...and an all-zero / zero-valued "code" is not a real ticker (no "0000.HK").
    assert market_data._hk_numeric_code("0") is None
    assert market_data._hk_numeric_code("00000") is None
    assert market_data._yahoo_stock_symbol("00000") == "00000"


def test_AC17_33_2_stooq_stock_symbol_maps_hk_numeric_codes() -> None:
    """AC17.33.2: HK numeric codes resolve to Stooq `<4-digit>.hk`; US tickers stay `.us`."""
    assert market_data._stooq_stock_symbol("01810") == "1810.hk"
    assert market_data._stooq_stock_symbol("00700") == "0700.hk"
    assert market_data._stooq_stock_symbol("AAPL") == "aapl.us"
    assert market_data._stooq_stock_symbol("0700.HK") == "0700.hk"


def test_select_validated_observation_paths() -> None:
    """AC11.10.4: Provider selection accepts fallback data and blocks disagreements."""
    observed_date = date(2026, 1, 5)
    primary = market_data.StockPriceObservation(
        symbol="AAPL",
        price=Decimal("100.00"),
        currency="USD",
        price_date=observed_date,
        source="primary",
    )
    secondary_close = market_data.StockPriceObservation(
        symbol="AAPL",
        price=Decimal("100.50"),
        currency="USD",
        price_date=observed_date,
        source="secondary",
    )
    secondary_far = market_data.StockPriceObservation(
        symbol="AAPL",
        price=Decimal("120.00"),
        currency="USD",
        price_date=observed_date,
        source="secondary",
    )

    assert (
        market_data._select_validated_observation(
            asset="AAPL", observed_date=observed_date, primary=None, secondary=secondary_close
        ).observation
        == secondary_close
    )
    assert (
        market_data._select_validated_observation(
            asset="AAPL", observed_date=observed_date, primary=primary, secondary=None
        ).observation
        == primary
    )

    validated = market_data._select_validated_observation(
        asset="AAPL",
        observed_date=observed_date,
        primary=primary,
        secondary=secondary_close,
    )
    assert isinstance(validated.observation, market_data.StockPriceObservation)
    assert validated.observation.source == "primary:validated:secondary"

    disagreement = market_data._select_validated_observation(
        asset="AAPL",
        observed_date=observed_date,
        primary=primary,
        secondary=secondary_far,
    )
    assert disagreement.observation is None
    assert disagreement.disagreement is not None
    assert disagreement.disagreement.to_dict()["asset"] == "AAPL"

    series = market_data._select_validated_observation_series(
        asset="AAPL",
        start_date=observed_date,
        end_date=observed_date,
        primary=[
            market_data.StockPriceObservation(
                symbol="AAPL",
                price=Decimal("99.00"),
                currency="USD",
                price_date=date(2026, 1, 4),
                source="primary",
            ),
            primary,
        ],
        secondary=[secondary_far],
        provider_success=True,
    )
    assert series.observations == []
    assert len(series.disagreements) == 1


def test_yahoo_response_parsers_select_latest_valid_observation() -> None:
    """AC11.10.4: Yahoo parsers ignore null/future closes and keep Decimal precision."""
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "usd"},
                    "timestamp": [
                        _epoch(date(2026, 1, 3)),
                        _epoch(date(2026, 1, 4)),
                        _epoch(date(2026, 1, 5)),
                    ],
                    "indicators": {"quote": [{"close": [1.23, None, 1.25]}]},
                }
            ]
        }
    }

    fx_rows = market_data._parse_yahoo_fx_response_series(payload, "USD", "SGD", date(2026, 1, 3), date(2026, 1, 4))
    assert len(fx_rows) == 1
    assert fx_rows[0].rate == Decimal("1.230000")
    assert fx_rows[0].rate_date == date(2026, 1, 3)

    stock_rows = market_data._parse_yahoo_stock_response_series(
        payload,
        "AAPL",
        date(2026, 1, 3),
        date(2026, 1, 5),
    )
    assert [row.price for row in stock_rows] == [Decimal("1.230000"), Decimal("1.250000")]
    assert stock_rows[-1].currency == "USD"
    assert stock_rows[-1].price_date == date(2026, 1, 5)

    assert (
        market_data._parse_yahoo_fx_response_series({"chart": {"result": []}}, "USD", "SGD", date.min, date.max) == []
    )
    assert market_data._parse_yahoo_stock_response_series({"chart": {"result": []}}, "AAPL", date.min, date.max) == []


def test_yahoo_response_series_parsers_return_bounded_rows() -> None:
    """AC11.10.8: Yahoo range parsers return only observations inside the requested window."""
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "usd"},
                    "timestamp": [
                        _epoch(date(2026, 1, 3)),
                        _epoch(date(2026, 1, 4)),
                        _epoch(date(2026, 1, 5)),
                    ],
                    "indicators": {"quote": [{"close": [1.23, None, 1.25]}]},
                }
            ]
        }
    }

    fx_rows = market_data._parse_yahoo_fx_response_series(
        payload,
        "USD",
        "SGD",
        date(2026, 1, 4),
        date(2026, 1, 5),
    )
    stock_rows = market_data._parse_yahoo_stock_response_series(
        payload,
        "AAPL",
        date(2026, 1, 4),
        date(2026, 1, 5),
    )

    assert [row.rate_date for row in fx_rows] == [date(2026, 1, 5)]
    assert fx_rows[0].rate == Decimal("1.250000")
    assert [row.price_date for row in stock_rows] == [date(2026, 1, 5)]
    assert stock_rows[0].currency == "USD"
    assert (
        market_data._parse_yahoo_fx_response_series(
            {"chart": {"result": []}}, "USD", "SGD", date(2026, 1, 4), date(2026, 1, 5)
        )
        == []
    )
    assert (
        market_data._parse_yahoo_stock_response_series(
            {"chart": {"result": []}}, "AAPL", date(2026, 1, 4), date(2026, 1, 5)
        )
        == []
    )


def test_stock_parsers_return_none_when_only_future_rows_exist() -> None:
    """AC11.10.3: Future-dated provider rows are ignored as unavailable for the requested day."""
    yahoo_payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [_epoch(date(2026, 1, 6))],
                    "indicators": {"quote": [{"close": [150.25]}]},
                }
            ]
        }
    }
    stooq_payload = "Date,Close\n2026-01-06,150.25\n"

    assert market_data._parse_yahoo_stock_response_series(yahoo_payload, "AAPL", date.min, date(2026, 1, 5)) == []
    assert market_data._parse_stooq_stock_csv_series(stooq_payload, "AAPL", date.min, date(2026, 1, 5)) == []


def test_stooq_csv_parsers_skip_invalid_rows_and_select_latest() -> None:
    """AC11.10.4: Stooq CSV parsers skip N/D and future rows."""
    payload = "\n".join(
        [
            "Date,Open,High,Low,Close,Volume",
            "2026-01-03,1,1,1,N/D,0",
            "2026-01-04,1,1,1,1.35001,0",
            "2026-01-05,1,1,1,1.36001,0",
        ]
    )

    fx_rows = market_data._parse_stooq_fx_csv_series(payload, "USD", "SGD", date(2026, 1, 3), date(2026, 1, 4))
    assert len(fx_rows) == 1
    assert fx_rows[0].rate == Decimal("1.350010")
    assert fx_rows[0].rate_date == date(2026, 1, 4)

    stock_rows = market_data._parse_stooq_stock_csv_series(payload, "AAPL", date(2026, 1, 3), date(2026, 1, 5))
    assert [row.price for row in stock_rows] == [Decimal("1.350010"), Decimal("1.360010")]
    assert stock_rows[-1].currency == "USD"
    assert stock_rows[-1].price_date == date(2026, 1, 5)

    assert (
        market_data._parse_stooq_fx_csv_series("Date,Close\n2026-01-01,N/D\n", "USD", "SGD", date.min, date.max) == []
    )
    assert market_data._parse_stooq_stock_csv_series("Date,Close\n2026-01-01,N/D\n", "AAPL", date.min, date.max) == []


def test_stooq_csv_series_parsers_skip_invalid_and_out_of_range_rows() -> None:
    """AC11.10.8: Stooq range parsers return bounded valid rows for bulk sync."""
    payload = "\n".join(
        [
            "Date,Open,High,Low,Close,Volume",
            "2026-01-03,1,1,1,1.33000,0",
            "2026-01-04,1,1,1,N/D,0",
            "2026-01-05,1,1,1,1.35000,0",
            "2026-01-06,1,1,1,1.36000,0",
        ]
    )

    fx_rows = market_data._parse_stooq_fx_csv_series(payload, "USD", "SGD", date(2026, 1, 4), date(2026, 1, 5))
    stock_rows = market_data._parse_stooq_stock_csv_series(payload, "AAPL", date(2026, 1, 4), date(2026, 1, 5))

    assert [row.rate_date for row in fx_rows] == [date(2026, 1, 5)]
    assert fx_rows[0].rate == Decimal("1.350000")
    assert [row.price_date for row in stock_rows] == [date(2026, 1, 5)]
    assert stock_rows[0].price == Decimal("1.350000")


async def test_persist_stock_price_returns_concurrent_row_after_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.1: Concurrent stock price inserts are resolved idempotently."""

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

    calls = 0

    async def fake_load(
        _db: object,
        _symbol: str,
        _requested_date: date,
    ) -> market_data._StoredStockPrice | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return market_data._StoredStockPrice(
            price=Decimal("150.000000"),
            currency="USD",
            price_date=date(2026, 1, 5),
            source="concurrent",
        )

    monkeypatch.setattr(market_data._store, "_load_stored_stock_price_on_date", fake_load)

    price = await market_data._persist_stock_price(
        FakeDb(),  # type: ignore[arg-type]
        market_data.StockPriceObservation(
            symbol="aapl",
            price=Decimal("160.000000"),
            currency="usd",
            price_date=date(2026, 1, 5),
            source="provider",
        ),
    )

    assert price == Decimal("150.000000")
    assert calls == 2


async def test_fetch_validated_provider_functions_cross_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.4: Validated fetches combine primary and secondary providers."""
    observed_date = date(2026, 1, 5)

    async def fake_yahoo_fx(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation:
        return market_data.FxRateObservation(base, quote, Decimal("1.350000"), requested_date, "yahoo_finance")

    async def fake_stooq_fx(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation:
        return market_data.FxRateObservation(base, quote, Decimal("1.351000"), requested_date, "stooq")

    async def fake_yahoo_stock(symbol: str, requested_date: date) -> market_data.StockPriceObservation:
        return market_data.StockPriceObservation(symbol, Decimal("100.00"), "USD", requested_date, "yahoo_finance")

    async def fake_stooq_stock(symbol: str, requested_date: date) -> market_data.StockPriceObservation:
        return market_data.StockPriceObservation(symbol, Decimal("100.10"), "USD", requested_date, "stooq")

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_or_derived_fx_rate", fake_yahoo_fx)
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_fx_rate", fake_stooq_fx)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_stock_price", fake_yahoo_stock)
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_stock_price", fake_stooq_stock)

    fx = await market_data._fetch_validated_fx_rate("USD", "SGD", observed_date)
    stock = await market_data._fetch_validated_stock_price("aapl", observed_date)

    assert isinstance(fx.observation, market_data.FxRateObservation)
    assert fx.observation.source == "yahoo_finance:validated:stooq"
    assert isinstance(stock.observation, market_data.StockPriceObservation)
    assert stock.observation.symbol == "AAPL"
    assert stock.observation.source == "yahoo_finance:validated:stooq"


async def test_fetch_validated_provider_series_functions_cross_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.8: Validated range fetches cross-validate rows by observation date."""
    observed_date = date(2026, 1, 5)

    async def fake_yahoo_fx(
        base: str,
        quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation]:
        return [market_data.FxRateObservation(base, quote, Decimal("1.350000"), observed_date, "yahoo_finance")]

    async def fake_stooq_fx(
        base: str,
        quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation]:
        return [market_data.FxRateObservation(base, quote, Decimal("1.351000"), observed_date, "stooq")]

    async def fake_yahoo_stock(
        symbol: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.StockPriceObservation]:
        return [market_data.StockPriceObservation(symbol, Decimal("100.00"), "USD", observed_date, "yahoo_finance")]

    async def fake_stooq_stock(
        symbol: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.StockPriceObservation]:
        return [market_data.StockPriceObservation(symbol, Decimal("100.10"), "USD", observed_date, "stooq")]

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_or_derived_fx_rate_series", fake_yahoo_fx)
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_fx_rate_series", fake_stooq_fx)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_stock_price_series", fake_yahoo_stock)
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_stock_price_series", fake_stooq_stock)

    fx = await market_data._fetch_validated_fx_rate_series("USD", "SGD", observed_date, observed_date)
    stock = await market_data._fetch_validated_stock_price_series("aapl", observed_date, observed_date)

    assert len(fx.observations) == 1
    assert isinstance(fx.observations[0], market_data.FxRateObservation)
    assert fx.observations[0].source == "yahoo_finance:validated:stooq"
    assert len(stock.observations) == 1
    assert isinstance(stock.observations[0], market_data.StockPriceObservation)
    assert stock.observations[0].source == "yahoo_finance:validated:stooq"


async def test_fetch_yahoo_or_derived_fx_rate_uses_inverse_and_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.2: Yahoo FX fetch derives inverse and bridge pairs when direct data is absent."""
    observed_date = date(2026, 1, 5)

    async def fake_inverse_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation | None:
        if (base, quote) == ("SGD", "USD"):
            return market_data.FxRateObservation(base, quote, Decimal("0.740000"), requested_date, "yahoo_finance")
        return None

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", fake_inverse_fetch)
    inverse = await market_data._fetch_yahoo_or_derived_fx_rate("USD", "SGD", observed_date)
    assert inverse is not None
    assert inverse.rate == Decimal("1.351351")
    assert inverse.source == "yahoo_finance:inverse"

    async def fake_bridge_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation | None:
        rates = {
            ("EUR", "USD"): Decimal("1.100000"),
            ("USD", "SGD"): Decimal("1.350000"),
        }
        rate = rates.get((base, quote))
        if rate is None:
            return None
        return market_data.FxRateObservation(base, quote, rate, requested_date, "yahoo_finance")

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", fake_bridge_fetch)
    bridge = await market_data._fetch_yahoo_or_derived_fx_rate("EUR", "SGD", observed_date)
    assert bridge is not None
    assert bridge.rate == Decimal("1.485000")
    assert bridge.source == "yahoo_finance:bridge:USD"

    missing = await market_data._fetch_yahoo_or_derived_fx_rate("GBP", "SGD", observed_date)
    assert missing is None


async def test_fetch_yahoo_or_derived_fx_rate_series_uses_inverse_bridge_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.8: Yahoo FX range fetch derives inverse and bridge rows for bulk sync."""
    observed_date = date(2026, 1, 5)

    async def fake_inverse_fetch(
        base: str,
        quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation] | None:
        if (base, quote) == ("SGD", "USD"):
            return [market_data.FxRateObservation(base, quote, Decimal("0.740000"), observed_date, "yahoo_finance")]
        return []

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", fake_inverse_fetch)
    inverse = await market_data._fetch_yahoo_or_derived_fx_rate_series("USD", "SGD", observed_date, observed_date)
    assert inverse is not None
    assert inverse[0].rate == Decimal("1.351351")
    assert inverse[0].source == "yahoo_finance:inverse"

    async def fake_bridge_fetch(
        base: str,
        quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation] | None:
        rates = {
            ("EUR", "USD"): Decimal("1.100000"),
            ("USD", "SGD"): Decimal("1.350000"),
        }
        rate = rates.get((base, quote))
        if rate is None:
            return []
        return [market_data.FxRateObservation(base, quote, rate, observed_date, "yahoo_finance")]

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", fake_bridge_fetch)
    bridge = await market_data._fetch_yahoo_or_derived_fx_rate_series("EUR", "SGD", observed_date, observed_date)
    assert bridge is not None
    assert bridge[0].rate == Decimal("1.485000")
    assert bridge[0].source == "yahoo_finance:bridge:USD"

    async def fake_failed_fetch(
        _base: str,
        _quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation] | None:
        return None

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", fake_failed_fetch)
    assert await market_data._fetch_yahoo_or_derived_fx_rate_series("GBP", "SGD", observed_date, observed_date) is None

    async def fake_pair_bridge_fetch(
        _base: str,
        _quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation] | None:
        return []

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", fake_pair_bridge_fetch)
    assert await market_data._fetch_yahoo_or_derived_fx_rate_series("USD", "SGD", observed_date, observed_date) == []

    async def fake_missing_bridge_leg_fetch(
        base: str,
        quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation] | None:
        if (base, quote) == ("EUR", "USD"):
            return [market_data.FxRateObservation(base, quote, Decimal("1.100000"), observed_date, "yahoo_finance")]
        return []

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", fake_missing_bridge_leg_fetch)
    assert await market_data._fetch_yahoo_or_derived_fx_rate_series("EUR", "SGD", observed_date, observed_date) == []

    async def fake_mismatched_bridge_fetch(
        base: str,
        quote: str,
        _start_date: date,
        _end_date: date,
    ) -> list[market_data.FxRateObservation] | None:
        if (base, quote) == ("EUR", "USD"):
            return [market_data.FxRateObservation(base, quote, Decimal("1.100000"), observed_date, "yahoo_finance")]
        if (base, quote) == ("USD", "SGD"):
            return [
                market_data.FxRateObservation(
                    base,
                    quote,
                    Decimal("1.350000"),
                    date(2026, 1, 6),
                    "yahoo_finance",
                )
            ]
        return []

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", fake_mismatched_bridge_fetch)
    assert await market_data._fetch_yahoo_or_derived_fx_rate_series("EUR", "SGD", observed_date, observed_date) == []


async def test_provider_http_wrappers_parse_success_and_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.4: HTTP wrappers hand responses to parsers and convert provider errors to misses."""

    class FakeResponse:
        def __init__(self, *, payload: dict[str, object] | None = None, text: str = "", error: bool = False) -> None:
            self._payload = payload or {}
            self.text = text
            self._error = error

        def json(self) -> dict[str, object]:
            return self._payload

        def raise_for_status(self) -> None:
            if self._error:
                raise httpx.HTTPStatusError(
                    "boom", request=httpx.Request("GET", "https://example.test"), response=httpx.Response(500)
                )

    class FakeAsyncClient:
        response: FakeResponse

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _url: str, *, params: dict[str, str]) -> FakeResponse:
            assert params["interval"] == "1d" if "interval" in params else params["i"] == "d"
            return self.response

    monkeypatch.setattr(market_data.httpx, "AsyncClient", FakeAsyncClient)
    chart_payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [_epoch(date(2026, 1, 5))],
                    "indicators": {"quote": [{"close": [150.25]}]},
                }
            ]
        }
    }
    csv_payload = "Date,Close\n2026-01-05,150.25\n"

    FakeAsyncClient.response = FakeResponse(payload=chart_payload)
    assert await market_data._fetch_yahoo_fx_rate("USD", "SGD", date(2026, 1, 5)) is not None
    assert await market_data._fetch_yahoo_stock_price("AAPL", date(2026, 1, 5)) is not None

    FakeAsyncClient.response = FakeResponse(text=csv_payload)
    assert await market_data._fetch_stooq_fx_rate("USD", "SGD", date(2026, 1, 5)) is not None
    assert await market_data._fetch_stooq_stock_price("AAPL", date(2026, 1, 5)) is not None

    FakeAsyncClient.response = FakeResponse(error=True)
    assert await market_data._fetch_yahoo_fx_rate("USD", "SGD", date(2026, 1, 5)) is None
    assert await market_data._fetch_yahoo_stock_price("AAPL", date(2026, 1, 5)) is None
    assert await market_data._fetch_stooq_fx_rate("USD", "SGD", date(2026, 1, 5)) is None
    assert await market_data._fetch_stooq_stock_price("AAPL", date(2026, 1, 5)) is None


async def test_provider_http_range_wrappers_parse_success_and_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.8: HTTP range wrappers parse bulk provider responses and report request failures."""

    class FakeResponse:
        def __init__(self, *, payload: dict[str, object] | None = None, text: str = "", error: bool = False) -> None:
            self._payload = payload or {}
            self.text = text
            self._error = error

        def json(self) -> dict[str, object]:
            return self._payload

        def raise_for_status(self) -> None:
            if self._error:
                raise httpx.HTTPStatusError(
                    "boom",
                    request=httpx.Request("GET", "https://example.test"),
                    response=httpx.Response(500),
                )

    class FakeAsyncClient:
        response: FakeResponse

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _url: str, *, params: dict[str, str]) -> FakeResponse:
            assert params["interval"] == "1d" if "interval" in params else params["i"] == "d"
            return self.response

    monkeypatch.setattr(market_data.httpx, "AsyncClient", FakeAsyncClient)
    chart_payload = {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [_epoch(date(2026, 1, 5))],
                    "indicators": {"quote": [{"close": [150.25]}]},
                }
            ]
        }
    }
    csv_payload = "Date,Close\n2026-01-05,150.25\n"

    FakeAsyncClient.response = FakeResponse(payload=chart_payload)
    assert await market_data._fetch_yahoo_fx_rate_series("USD", "SGD", date(2026, 1, 5), date(2026, 1, 5))
    assert await market_data._fetch_yahoo_stock_price_series("AAPL", date(2026, 1, 5), date(2026, 1, 5))

    FakeAsyncClient.response = FakeResponse(text=csv_payload)
    assert await market_data._fetch_stooq_fx_rate_series("USD", "SGD", date(2026, 1, 5), date(2026, 1, 5))
    assert await market_data._fetch_stooq_stock_price_series("AAPL", date(2026, 1, 5), date(2026, 1, 5))

    FakeAsyncClient.response = FakeResponse(error=True)
    assert await market_data._fetch_yahoo_fx_rate_series("USD", "SGD", date(2026, 1, 5), date(2026, 1, 5)) is None
    assert await market_data._fetch_yahoo_stock_price_series("AAPL", date(2026, 1, 5), date(2026, 1, 5)) is None
    assert await market_data._fetch_stooq_fx_rate_series("USD", "SGD", date(2026, 1, 5), date(2026, 1, 5)) is None
    assert await market_data._fetch_stooq_stock_price_series("AAPL", date(2026, 1, 5), date(2026, 1, 5)) is None


def test_looks_like_ticker_accepts_real_tickers_rejects_free_text() -> None:
    """AC17.15.1: Plausible tickers pass; brokerage fund-name free text is rejected."""
    for symbol in ("AAPL", "MSFT", "BRK.B", "0700.HK", "USDSGD", "^GSPC", "aapl"):
        assert market_data._looks_like_ticker(symbol), symbol

    for symbol in (
        "CSOP USD MONEY MARKET FUND SGX296797238",
        "Fullerton SGD Cash Fund",
        "",
        "   ",
        "A" * 40,
    ):
        assert not market_data._looks_like_ticker(symbol), symbol


async def test_yahoo_stock_fetch_short_circuits_for_non_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC17.15.2: A non-ticker identifier skips the Yahoo request and returns None."""

    async def fail_if_called(*_args: object, **_kwargs: object) -> httpx.Response | None:
        raise AssertionError("Yahoo provider must not be queried for non-ticker identifiers")

    monkeypatch.setattr(market_data._providers, "_fetch_provider_response", fail_if_called)

    result = await market_data._fetch_yahoo_stock_price_series(
        "CSOP USD MONEY MARKET FUND SGX296797238",
        date(2026, 1, 1),
        date(2026, 1, 5),
    )
    assert result is None
