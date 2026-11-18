from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx
import pytest
from common.testing import money_amount
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.pricing.extension.market_data import _providers
from src.pricing.orm.market_data import FxRate, StockPrice

_FIXTURES = Path(__file__).parent / "fixtures"
_RECORDED_PAYLOADS = {"USDSGD=X": "yahoo_chart_usdsgd_2024-06-03.json", "IBM": "yahoo_chart_ibm_2024-06-03.json"}
_AS_OF = date(2024, 6, 3)
_EXPECTED_USD_SGD = Decimal("1.345000")
_EXPECTED_IBM_CLOSE = Decimal("165.279999")
_EXPECTED_VALUE_SGD = Decimal("444.60")


@pytest.fixture
def recorded_provider_replay(monkeypatch):
    payloads = {suffix: json.loads((_FIXTURES / name).read_text(encoding="utf-8")) for suffix, name in _RECORDED_PAYLOADS.items()}

    async def replay(url, params, *, failure_message, log_context):
        return next((httpx.Response(200, json=p, request=httpx.Request("GET", url, params=params)) for s, p in payloads.items() if url.endswith(f"/{s}")), None)

    monkeypatch.setattr(_providers, "_fetch_provider_response", replay)
    monkeypatch.setattr(settings, "market_data_lazy_fetch_enabled", True)


async def test_recorded_provider_fx_and_stock_path_converts_exactly(client, db: AsyncSession, recorded_provider_replay) -> None:
    imp = await client.post("/portfolio/brokerage-imports", json={"filename": "recorded-price-path-ibm.json", "source_document_id": f"recorded-price-path-{uuid.uuid4()}", "payload": {"institution": "Recorded Price Path Broker", "statement": {"period_end": _AS_OF.isoformat(), "currency": "USD"}, "positions": [{"symbol": "IBM", "broker": "Recorded Price Path Broker", "quantity": "2", "market_value": "20.00", "currency": "USD"}]}})
    rep = await client.get(f"/reports/balance-sheet?as_of_date={_AS_OF.isoformat()}&currency=SGD")
    hold = await client.get(f"/portfolio/holdings?as_of_date={_AS_OF.isoformat()}")
    fx_row = (await db.execute(select(FxRate).where(FxRate.base_currency == "USD", FxRate.quote_currency == "SGD", FxRate.rate_date == _AS_OF))).scalar_one()
    price_row = (await db.execute(select(StockPrice).where(StockPrice.symbol == "IBM", StockPrice.price_date == _AS_OF))).scalar_one()
    ibm = next((i for i in hold.json()["items"] if i["asset_identifier"] == "IBM"), None)
    assert (
        (imp.status_code, imp.json()["parsed_positions"]),
        (rep.status_code, money_amount(rep.json()["total_assets"]), rep.json()["is_balanced"]),
        (fx_row.rate, fx_row.source, price_row.price),
        (hold.status_code, ibm is not None and money_amount(ibm["market_value"]), ibm["currency"], ibm["native_currency"]),
    ) == ((200, 1), (200, _EXPECTED_VALUE_SGD, True), (_EXPECTED_USD_SGD, "yahoo_finance", _EXPECTED_IBM_CLOSE), (200, _EXPECTED_VALUE_SGD, "SGD", "USD"))


def test_recorded_payloads_carry_the_pinned_closes() -> None:
    def close_on(name: str) -> Decimal:
        result = json.loads((_FIXTURES / _RECORDED_PAYLOADS[name]).read_text(encoding="utf-8"))["chart"]["result"][0]
        return next(Decimal(str(c)) for ts, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"], strict=False) if datetime.fromtimestamp(int(ts), UTC).date() == _AS_OF and c is not None)

    assert (
        close_on("USDSGD=X").quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        close_on("IBM").quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        (Decimal("2") * _EXPECTED_IBM_CLOSE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        (Decimal("2") * _EXPECTED_IBM_CLOSE * _EXPECTED_USD_SGD).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    ) == (_EXPECTED_USD_SGD, _EXPECTED_IBM_CLOSE, Decimal("330.56"), _EXPECTED_VALUE_SGD)
