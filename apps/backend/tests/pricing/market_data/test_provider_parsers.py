from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from src.pricing.extension import market_data

_epoch = lambda value: int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def test_market_data_helper_boundaries_and_symbols() -> None:
    assert (
        market_data._iter_dates(date(2026, 1, 3), date(2026, 1, 1)),
        market_data._parse_fx_pair(" usd / sgd "),
        market_data._default_start_date(date(2026, 1, 8)),
        market_data._incremental_start(date(2026, 1, 3), None, date(2026, 1, 5)),
        market_data._incremental_start(date(2026, 1, 6), None, date(2026, 1, 5)),
        market_data._relative_difference(Decimal("0"), Decimal("0")),
        market_data._relative_difference(Decimal("100"), Decimal("98")),
        market_data._stooq_fx_symbol("USD", "SGD"),
        market_data._normalize_utc(datetime(2026, 1, 5)).tzinfo,
        [market_data._yahoo_stock_symbol(s) for s in ("01810", "00700", "700", "AAPL", "brk.b", "1810.HK", "10000", "00000")],
        [market_data._hk_numeric_code(s) for s in ("10000", "0", "00000")],
        [market_data._stooq_stock_symbol(s) for s in ("01810", "00700", "AAPL", "0700.HK")],
    ) == (
        [],
        ("USD", "SGD"),
        date(2026, 1, 2),
        date(2026, 1, 4),
        None,
        Decimal("0"),
        Decimal("0.020000"),
        "usdsgd",
        UTC,
        ["1810.HK", "0700.HK", "0700.HK", "AAPL", "BRK.B", "1810.HK", "10000.HK", "00000"],
        ["10000", None, None],
        ["1810.hk", "0700.hk", "aapl.us", "0700.hk"],
    )
    with pytest.raises(ValueError, match="expected BASE/QUOTE"):
        market_data._parse_fx_pair("USD-SGD")


def test_observation_selection_and_provider_series_parsers() -> None:
    d4, d5, d6 = date(2026, 1, 4), date(2026, 1, 5), date(2026, 1, 6)
    pri = market_data.StockPriceObservation("AAPL", Decimal("100.00"), "USD", d5, "primary")
    sec_ok = market_data.StockPriceObservation("AAPL", Decimal("100.50"), "USD", d5, "secondary")
    sec_far = market_data.StockPriceObservation("AAPL", Decimal("120.00"), "USD", d5, "secondary")
    val = market_data._select_validated_observation(asset="AAPL", observed_date=d5, primary=pri, secondary=sec_ok)
    dis = market_data._select_validated_observation(asset="AAPL", observed_date=d5, primary=pri, secondary=sec_far)
    series = market_data._select_validated_observation_series(asset="AAPL", start_date=d5, end_date=d5, primary=[market_data.StockPriceObservation("AAPL", Decimal("99.00"), "USD", d4, "primary"), pri], secondary=[sec_far], provider_success=True)
    chart = {"chart": {"result": [{"meta": {"currency": "usd"}, "timestamp": [_epoch(date(2026, 1, 3)), _epoch(d4), _epoch(d5)], "indicators": {"quote": [{"close": [1.23, None, 1.25]}]}}]}}
    csv_3 = "Date,Open,High,Low,Close,Volume\n2026-01-03,1,1,1,N/D,0\n2026-01-04,1,1,1,1.35001,0\n2026-01-05,1,1,1,1.36001,0"
    csv_4 = "Date,Open,High,Low,Close,Volume\n2026-01-03,1,1,1,1.33000,0\n2026-01-04,1,1,1,N/D,0\n2026-01-05,1,1,1,1.35000,0\n2026-01-06,1,1,1,1.36000,0"
    assert (
        market_data._select_validated_observation(asset="AAPL", observed_date=d5, primary=None, secondary=sec_ok).observation,
        market_data._select_validated_observation(asset="AAPL", observed_date=d5, primary=pri, secondary=None).observation,
        (isinstance(val.observation, market_data.StockPriceObservation), val.observation.source),
        (dis.observation, dis.disagreement is not None, dis.disagreement.to_dict()["asset"]),
        (series.observations, len(series.disagreements)),
        [(r.rate_date, r.rate) for r in market_data._parse_yahoo_fx_response_series(chart, "USD", "SGD", date(2026, 1, 3), d4)],
        [(r.price_date, r.price, r.currency) for r in market_data._parse_yahoo_stock_response_series(chart, "AAPL", date(2026, 1, 3), d5)],
        [(r.rate_date, r.rate) for r in market_data._parse_yahoo_fx_response_series(chart, "USD", "SGD", d4, d5)],
        [(r.price_date, r.price, r.currency) for r in market_data._parse_yahoo_stock_response_series(chart, "AAPL", d4, d5)],
        market_data._parse_yahoo_fx_response_series({"chart": {"result": []}}, "USD", "SGD", date.min, date.max),
        market_data._parse_yahoo_stock_response_series({"chart": {"result": []}}, "AAPL", date.min, date.max),
        market_data._parse_yahoo_stock_response_series({"chart": {"result": [{"meta": {"currency": "USD"}, "timestamp": [_epoch(d6)], "indicators": {"quote": [{"close": [150.25]}]}}]}}, "AAPL", date.min, d5),
        market_data._parse_stooq_stock_csv_series("Date,Close\n2026-01-06,150.25\n", "AAPL", date.min, d5),
        [(r.rate_date, r.rate) for r in market_data._parse_stooq_fx_csv_series(csv_3, "USD", "SGD", date(2026, 1, 3), d4)],
        [(r.price_date, r.price, r.currency) for r in market_data._parse_stooq_stock_csv_series(csv_3, "AAPL", date(2026, 1, 3), d5)],
        market_data._parse_stooq_fx_csv_series("Date,Close\n2026-01-01,N/D\n", "USD", "SGD", date.min, date.max),
        market_data._parse_stooq_stock_csv_series("Date,Close\n2026-01-01,N/D\n", "AAPL", date.min, date.max),
        [(r.rate_date, r.rate) for r in market_data._parse_stooq_fx_csv_series(csv_4, "USD", "SGD", d4, d5)],
        [(r.price_date, r.price) for r in market_data._parse_stooq_stock_csv_series(csv_4, "AAPL", d4, d5)],
    ) == (
        sec_ok,
        pri,
        (True, "primary:validated:secondary"),
        (None, True, "AAPL"),
        ([], 1),
        [(date(2026, 1, 3), Decimal("1.230000"))],
        [(date(2026, 1, 3), Decimal("1.230000"), "USD"), (d5, Decimal("1.250000"), "USD")],
        [(d5, Decimal("1.250000"))],
        [(d5, Decimal("1.250000"), "USD")],
        [],
        [],
        [],
        [],
        [(d4, Decimal("1.350010"))],
        [(d4, Decimal("1.350010"), "USD"), (d5, Decimal("1.360010"), "USD")],
        [],
        [],
        [(d5, Decimal("1.350000"))],
        [(d5, Decimal("1.350000"))],
    )


async def test_persist_stock_price_returns_concurrent_row_after_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class NestedTransaction:
        async def __aenter__(self) -> "NestedTransaction":
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    class FakeDb:
        add = lambda _s, _r: None
        rollback = lambda _s: _noop()
        begin_nested = lambda _s: NestedTransaction()

        async def flush(self) -> None:
            raise IntegrityError("insert", {}, Exception("duplicate"))

    async def _noop() -> None:
        return None

    calls = 0

    async def fake_load(_db: object, _symbol: str, _requested_date: date) -> market_data._StoredStockPrice | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else market_data._StoredStockPrice(Decimal("150.000000"), "USD", date(2026, 1, 5), "concurrent")

    monkeypatch.setattr(market_data._store, "_load_stored_stock_price_on_date", fake_load)
    price = await market_data._persist_stock_price(FakeDb(), market_data.StockPriceObservation("aapl", Decimal("160.000000"), "usd", date(2026, 1, 5), "provider"))
    assert (price, calls) == (Decimal("150.000000"), 2)


async def test_fetch_validated_provider_single_and_series_cross_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    d5 = date(2026, 1, 5)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_or_derived_fx_rate", lambda b, q, d: _coro(market_data.FxRateObservation(b, q, Decimal("1.350000"), d, "yahoo_finance")))
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_fx_rate", lambda b, q, d: _coro(market_data.FxRateObservation(b, q, Decimal("1.351000"), d, "stooq")))
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_stock_price", lambda s, d: _coro(market_data.StockPriceObservation(s, Decimal("100.00"), "USD", d, "yahoo_finance")))
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_stock_price", lambda s, d: _coro(market_data.StockPriceObservation(s, Decimal("100.10"), "USD", d, "stooq")))
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_or_derived_fx_rate_series", lambda b, q, _s, _e: _coro([market_data.FxRateObservation(b, q, Decimal("1.350000"), d5, "yahoo_finance")]))
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_fx_rate_series", lambda b, q, _s, _e: _coro([market_data.FxRateObservation(b, q, Decimal("1.351000"), d5, "stooq")]))
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_stock_price_series", lambda s, _s, _e: _coro([market_data.StockPriceObservation(s, Decimal("100.00"), "USD", d5, "yahoo_finance")]))
    monkeypatch.setattr(market_data._providers, "_fetch_stooq_stock_price_series", lambda s, _s, _e: _coro([market_data.StockPriceObservation(s, Decimal("100.10"), "USD", d5, "stooq")]))
    fx, stock = await market_data._fetch_validated_fx_rate("USD", "SGD", d5), await market_data._fetch_validated_stock_price("aapl", d5)
    fx_s, stock_s = await market_data._fetch_validated_fx_rate_series("USD", "SGD", d5, d5), await market_data._fetch_validated_stock_price_series("aapl", d5, d5)
    assert (fx.observation.source, (stock.observation.symbol, stock.observation.source), fx_s.observations[0].source, stock_s.observations[0].source) == (
        "yahoo_finance:validated:stooq",
        ("AAPL", "yahoo_finance:validated:stooq"),
        "yahoo_finance:validated:stooq",
        "yahoo_finance:validated:stooq",
    )


async def _coro(value):
    return value


async def test_fetch_yahoo_or_derived_fx_single_and_series_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    d5, d6 = date(2026, 1, 5), date(2026, 1, 6)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", lambda b, q, d: _coro(market_data.FxRateObservation(b, q, Decimal("0.740000"), d, "yahoo_finance") if (b, q) == ("SGD", "USD") else None))
    inv = await market_data._fetch_yahoo_or_derived_fx_rate("USD", "SGD", d5)
    rates = {("EUR", "USD"): Decimal("1.100000"), ("USD", "SGD"): Decimal("1.350000")}
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate", lambda b, q, d: _coro(market_data.FxRateObservation(b, q, rates[(b, q)], d, "yahoo_finance") if (b, q) in rates else None))
    br = await market_data._fetch_yahoo_or_derived_fx_rate("EUR", "SGD", d5)
    miss = await market_data._fetch_yahoo_or_derived_fx_rate("GBP", "SGD", d5)

    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", lambda b, q, _s, _e: _coro([market_data.FxRateObservation(b, q, Decimal("0.740000"), d5, "yahoo_finance")] if (b, q) == ("SGD", "USD") else []))
    inv_s = await market_data._fetch_yahoo_or_derived_fx_rate_series("USD", "SGD", d5, d5)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", lambda b, q, _s, _e: _coro([market_data.FxRateObservation(b, q, rates[(b, q)], d5, "yahoo_finance")] if (b, q) in rates else []))
    br_s = await market_data._fetch_yahoo_or_derived_fx_rate_series("EUR", "SGD", d5, d5)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", lambda *_a: _coro(None))
    none_s = await market_data._fetch_yahoo_or_derived_fx_rate_series("GBP", "SGD", d5, d5)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", lambda *_a: _coro([]))
    empty_s = await market_data._fetch_yahoo_or_derived_fx_rate_series("USD", "SGD", d5, d5)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", lambda b, q, _s, _e: _coro([market_data.FxRateObservation(b, q, Decimal("1.100000"), d5, "yahoo_finance")] if (b, q) == ("EUR", "USD") else []))
    one_leg = await market_data._fetch_yahoo_or_derived_fx_rate_series("EUR", "SGD", d5, d5)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_fx_rate_series", lambda b, q, _s, _e: _coro([market_data.FxRateObservation(b, q, Decimal("1.100000" if b == "EUR" else "1.350000"), d5 if b == "EUR" else d6, "yahoo_finance")] if (b, q) in rates else []))
    mismatched = await market_data._fetch_yahoo_or_derived_fx_rate_series("EUR", "SGD", d5, d5)
    assert (
        (inv.rate, inv.source),
        (br.rate, br.source),
        miss,
        (inv_s[0].rate, inv_s[0].source),
        (br_s[0].rate, br_s[0].source),
        none_s,
        empty_s,
        one_leg,
        mismatched,
    ) == (
        (Decimal("1.351351"), "yahoo_finance:inverse"),
        (Decimal("1.485000"), "yahoo_finance:bridge:USD"),
        None,
        (Decimal("1.351351"), "yahoo_finance:inverse"),
        (Decimal("1.485000"), "yahoo_finance:bridge:USD"),
        None,
        [],
        [],
        [],
    )


async def test_provider_http_wrappers_and_non_ticker_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, *, payload: dict[str, object] | None = None, text: str = "", error: bool = False) -> None:
            self._payload, self.text, self._error = payload or {}, text, error

        def json(self) -> dict[str, object]:
            return self._payload

        def raise_for_status(self) -> None:
            if self._error:
                raise httpx.HTTPStatusError("boom", request=httpx.Request("GET", "https://example.test"), response=httpx.Response(500))

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

    d5 = date(2026, 1, 5)
    chart_payload = {"chart": {"result": [{"meta": {"currency": "USD"}, "timestamp": [_epoch(d5)], "indicators": {"quote": [{"close": [150.25]}]}}]}}
    csv_payload = "Date,Close\n2026-01-05,150.25\n"
    monkeypatch.setattr(market_data.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.response = FakeResponse(payload=chart_payload)
    ok_yahoo = [await market_data._fetch_yahoo_fx_rate("USD", "SGD", d5), await market_data._fetch_yahoo_stock_price("AAPL", d5), await market_data._fetch_yahoo_fx_rate_series("USD", "SGD", d5, d5), await market_data._fetch_yahoo_stock_price_series("AAPL", d5, d5)]
    FakeAsyncClient.response = FakeResponse(text=csv_payload)
    ok_stooq = [await market_data._fetch_stooq_fx_rate("USD", "SGD", d5), await market_data._fetch_stooq_stock_price("AAPL", d5), await market_data._fetch_stooq_fx_rate_series("USD", "SGD", d5, d5), await market_data._fetch_stooq_stock_price_series("AAPL", d5, d5)]
    FakeAsyncClient.response = FakeResponse(error=True)
    err_all = [await fn(*args) for fn, args in ((market_data._fetch_yahoo_fx_rate, ("USD", "SGD", d5)), (market_data._fetch_yahoo_stock_price, ("AAPL", d5)), (market_data._fetch_stooq_fx_rate, ("USD", "SGD", d5)), (market_data._fetch_stooq_stock_price, ("AAPL", d5)), (market_data._fetch_yahoo_fx_rate_series, ("USD", "SGD", d5, d5)), (market_data._fetch_yahoo_stock_price_series, ("AAPL", d5, d5)), (market_data._fetch_stooq_fx_rate_series, ("USD", "SGD", d5, d5)), (market_data._fetch_stooq_stock_price_series, ("AAPL", d5, d5)))]
    assert (all(ok_yahoo), all(ok_stooq), err_all) == (True, True, [None] * 8)

    assert all(market_data._looks_like_ticker(s) for s in ("AAPL", "MSFT", "BRK.B", "0700.HK", "USDSGD", "^GSPC", "aapl"))
    assert not any(market_data._looks_like_ticker(s) for s in ("CSOP USD MONEY MARKET FUND SGX296797238", "Fullerton SGD Cash Fund", "", "   ", "A" * 40))
    monkeypatch.setattr(market_data._providers, "_fetch_provider_response", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("Yahoo provider must not be queried for non-ticker identifiers")))
    assert await market_data._fetch_yahoo_stock_price_series("CSOP USD MONEY MARKET FUND SGX296797238", date(2026, 1, 1), d5) is None
