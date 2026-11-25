from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.pricing import get_exchange_rate
from src.pricing.extension import market_data
from src.pricing.orm.market_data import FxRate


async def _coro(value):
    return value


async def test_get_exchange_rate_and_resolve_missing_fx_rate_paths(db: AsyncSession, monkeypatch) -> None:
    d30 = date(2025, 6, 30)
    monkeypatch.setattr(settings, "market_data_lazy_fetch_enabled", True)
    monkeypatch.setattr(
        market_data._providers,
        "_fetch_yahoo_fx_rate",
        lambda b, q, d: _coro(market_data.FxRateObservation(b, q, Decimal("0.173077"), d, "yahoo_finance")),
    )
    lazy_rate = await get_exchange_rate(db, "HKD", "SGD", d30, lazy_load=True)
    provider_rate = (
        await db.execute(
            select(FxRate).where(FxRate.base_currency == "HKD", FxRate.quote_currency == "SGD", FxRate.rate_date == d30)
        )
    ).scalar_one()

    db.add(
        FxRate(
            base_currency="EUR",
            quote_currency="SGD",
            rate=Decimal("1.450000"),
            rate_date=date(2025, 6, 29),
            source="test",
        )
    )
    await db.commit()
    stored_rate = await market_data.resolve_missing_fx_rate(db, "eur", "sgd", d30)
    identity_rate = await market_data.resolve_missing_fx_rate(db, "sgd", "SGD", d30)
    monkeypatch.setattr(market_data._providers, "_fetch_yahoo_or_derived_fx_rate", lambda *_a: _coro(None))
    missing_rate = await market_data.resolve_missing_fx_rate(db, "GBP", "SGD", d30)
    assert ((lazy_rate, provider_rate.rate, provider_rate.source), identity_rate, stored_rate, missing_rate) == (
        (Decimal("0.173077"), Decimal("0.173077"), "yahoo_finance"),
        Decimal("1"),
        Decimal("1.450000"),
        None,
    )


async def test_persist_fx_rate_existing_and_concurrent_insert(db: AsyncSession) -> None:
    d30 = date(2025, 6, 30)
    db.add(FxRate(base_currency="HKD", quote_currency="SGD", rate=Decimal("0.173000"), rate_date=d30, source="manual"))
    await db.commit()
    kept = await market_data._persist_fx_rate(
        db, market_data.FxRateObservation("hkd", "sgd", Decimal("0.180000"), d30, "yahoo_finance")
    )
    row = (
        await db.execute(select(FxRate).where(FxRate.base_currency == "HKD", FxRate.quote_currency == "SGD"))
    ).scalar_one()
    assert (kept, row.rate, row.source) == (Decimal("0.173000"), Decimal("0.173000"), "manual")

    class NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    class FakeSession:
        def __init__(self, row_on_second):
            self.execute_calls, self.rolled_back, self.added, self._row = 0, False, None, row_on_second

        async def execute(self, _stmt):
            self.execute_calls += 1
            val = None if self.execute_calls == 1 else self._row
            return type("_Res", (), {"one_or_none": lambda _s: val})()

        def add(self, value):
            self.added = value

        async def flush(self):
            raise IntegrityError("insert fx", {}, Exception("duplicate"))

        async def rollback(self):
            self.rolled_back = True

        def begin_nested(self):
            return NestedTransaction()

    concurrent = FakeSession(
        type("_Row", (), {"rate": Decimal("0.173500"), "rate_date": d30, "source": "concurrent"})()
    )
    obs = market_data.FxRateObservation("HKD", "SGD", Decimal("0.173077"), d30, "yahoo_finance")
    res = await market_data._persist_fx_rate(concurrent, obs)
    assert (res, concurrent.rolled_back, concurrent.added is not None) == (Decimal("0.173500"), False, True)
    with pytest.raises(IntegrityError):
        await market_data._persist_fx_rate(FakeSession(None), obs)


@pytest.mark.parametrize(
    ("bridge", "table", "expected"),
    [
        (
            "USD",
            {("SGD", "HKD"): ("5.800000", date(2025, 6, 30))},
            ("0.172414", date(2025, 6, 30), "yahoo_finance:inverse"),
        ),
        (
            "USD",
            {("HKD", "USD"): ("0.128205", date(2025, 6, 29)), ("USD", "SGD"): ("1.350000", date(2025, 6, 30))},
            ("0.173077", date(2025, 6, 30), "yahoo_finance:bridge:USD"),
        ),
        ("SGD", {}, None),
        ("USD", {("HKD", "USD"): ("0.128205", date(2025, 6, 30))}, None),
    ],
)
async def test_fetch_yahoo_or_derived_fx_rate_variants(monkeypatch, bridge, table, expected) -> None:
    monkeypatch.setattr(settings, "market_data_fx_bridge_currency", bridge)
    monkeypatch.setattr(
        market_data._providers,
        "_fetch_yahoo_fx_rate",
        lambda b, q, _d: _coro(
            market_data.FxRateObservation(b, q, Decimal(table[(b, q)][0]), table[(b, q)][1], "yahoo_finance")
            if (b, q) in table
            else None
        ),
    )
    result = await market_data._fetch_yahoo_or_derived_fx_rate("HKD", "SGD", date(2025, 6, 30))
    assert result == (
        None
        if expected is None
        else market_data.FxRateObservation("HKD", "SGD", Decimal(expected[0]), expected[1], expected[2])
    )


async def test_fetch_yahoo_fx_rate_http_and_parse_selection(monkeypatch) -> None:
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

    def make_client(fail: bool):
        class _Client:
            def __init__(self, *, timeout, headers):
                self.timeout, self.headers = timeout, headers

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

            async def get(self, url, params):
                if fail:
                    raise httpx.ConnectError("offline", request=httpx.Request("GET", url))
                calls.append((self.timeout, self.headers, url, params))
                return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

        return _Client

    monkeypatch.setattr(market_data.httpx, "AsyncClient", make_client(False))
    ok = await market_data._fetch_yahoo_fx_rate("HKD", "SGD", date(2025, 6, 30))
    monkeypatch.setattr(market_data.httpx, "AsyncClient", make_client(True))
    err = await market_data._fetch_yahoo_fx_rate("HKD", "SGD", date(2025, 6, 30))
    rows = market_data._parse_yahoo_fx_response_series(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [
                            market_data._date_to_epoch(date(2025, 6, 28)),
                            market_data._date_to_epoch(date(2025, 6, 29)),
                            market_data._date_to_epoch(date(2025, 7, 1)),
                        ],
                        "indicators": {"quote": [{"close": [None, 0.1730774, 0.2]}]},
                    }
                ]
            }
        },
        "HKD",
        "SGD",
        date.min,
        date(2025, 6, 30),
    )
    assert (
        ok,
        calls[0],
        err,
        max(rows, key=lambda item: item.rate_date, default=None),
        market_data._parse_yahoo_fx_response_series({}, "HKD", "SGD", date.min, date(2025, 6, 30)),
        market_data._parse_yahoo_fx_response_series(
            {
                "chart": {
                    "result": [
                        {
                            "timestamp": [market_data._date_to_epoch(date(2025, 7, 1))],
                            "indicators": {"quote": [{"close": [0.2]}]},
                        }
                    ]
                }
            },
            "HKD",
            "SGD",
            date.min,
            date(2025, 6, 30),
        ),
    ) == (
        market_data.FxRateObservation("HKD", "SGD", Decimal("0.173077"), date(2025, 6, 29), "yahoo_finance"),
        (
            settings.market_data_yahoo_timeout_seconds,
            {"User-Agent": "finance-report-audit/1.0"},
            "https://query1.finance.yahoo.com/v8/finance/chart/HKDSGD=X",
            calls[0][3],
        ),
        None,
        market_data.FxRateObservation("HKD", "SGD", Decimal("0.173077"), date(2025, 6, 29), "yahoo_finance"),
        [],
        [],
    )
    assert calls[0][3]["interval"] == "1d"
