"""Blocking FX/market-data real-path value proof on RECORDED provider data.

#1826 G-fx-real-path: the backend suite globally disables provider fetches
(``disable_external_market_data_fetch`` autouse), and the only e2e walking the
real price path was itself exempt from value assertions — the FX lane was
doubly dark. This journey closes it IN THE BLOCKING LANE:

- lazy fetch is explicitly ENABLED (prod-shaped configuration),
- genuinely recorded Yahoo chart payloads (captured 2026-07-14 for the
  2024-06-03 window, committed under ``fixtures/``) are replayed at the
  provider-response seam (``_providers._fetch_provider_response``), so the
  provider PARSING, validation, and persistence code runs for real — only the
  network hop is replaced; the secondary (Stooq) source returns None, a
  tolerated single-source condition,
- the full product path runs over HTTP: brokerage position import -> balance
  sheet request -> report-time freshness sync -> recorded provider parse ->
  FX/stock persistence -> currency conversion,
- and the CONVERTED value is asserted EXACTLY, hand-derived from the recorded
  closes (never from pipeline output):

    IBM 2024-06-03 close  165.27999877929688 -> 6dp HALF_UP -> 165.279999 USD
    USD/SGD 2024-06-03    1.3450000286102295 -> 6dp HALF_UP -> 1.345000
    2 shares x 165.279999 USD = 330.559998 -> 330.56 USD (money 2dp)
    330.559998 x 1.345000   = 444.60319731 -> 444.60 SGD (money 2dp)

AC-pricing.marketdata.13 (proof_kind=exact) anchors this test; the staging
proof ``market-data-provider-price-path`` lists that AC, which is how the
critical-value ratchet pair ``investment-performance::market-data-provider-
price-path`` earns its value oracle.
"""

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

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED_PAYLOADS = {
    "USDSGD=X": "yahoo_chart_usdsgd_2024-06-03.json",
    "IBM": "yahoo_chart_ibm_2024-06-03.json",
}

AS_OF = date(2024, 6, 3)
POSITION_QUANTITY = "2"
STALE_MARKET_VALUE_USD = Decimal("20.00")

# Hand-derived oracle constants (see module docstring for the derivation from
# the recorded closes — independent of any pipeline output).
EXPECTED_USD_SGD_RATE = Decimal("1.345000")
EXPECTED_IBM_CLOSE = Decimal("165.279999")
EXPECTED_POSITION_VALUE_USD = Decimal("330.56")
EXPECTED_POSITION_VALUE_SGD = Decimal("444.60")


@pytest.fixture
def recorded_provider_replay(monkeypatch):
    """Replay recorded Yahoo payloads at the provider-response seam.

    Yahoo URLs are answered from the committed recordings (a real
    ``httpx.Response``, so ``response.json()`` and every parse/validate step
    run unchanged); any other provider URL (Stooq secondary) returns ``None``
    — the same tolerated condition as that provider being down. No live
    network can be reached.
    """
    payloads = {
        suffix: json.loads((FIXTURES / name).read_text(encoding="utf-8")) for suffix, name in RECORDED_PAYLOADS.items()
    }

    async def replay(url, params, *, failure_message, log_context):
        for suffix, payload in payloads.items():
            if url.endswith(f"/{suffix}"):
                request = httpx.Request("GET", url, params=params)
                return httpx.Response(200, json=payload, request=request)
        return None  # secondary provider (Stooq) unavailable — tolerated

    monkeypatch.setattr(_providers, "_fetch_provider_response", replay)
    # Re-enable the prod-shaped lazy fetch that the autouse fixture disables:
    # this test EXISTS to exercise the real fetch-enabled path (#1826).
    monkeypatch.setattr(settings, "market_data_lazy_fetch_enabled", True)


async def test_recorded_provider_fx_and_stock_path_converts_exactly(
    client, db: AsyncSession, recorded_provider_replay
) -> None:
    """AC-pricing.marketdata.13: a stale USD position is repriced from the
    RECORDED provider closes and lands on the SGD balance sheet at the exact
    hand-derived converted value — the number, not just the flow."""
    import_response = await client.post(
        "/portfolio/brokerage/import",
        json={
            "filename": "recorded-price-path-ibm.json",
            "source_document_id": f"recorded-price-path-{uuid.uuid4()}",
            "payload": {
                "institution": "Recorded Price Path Broker",
                "statement": {"period_end": AS_OF.isoformat(), "currency": "USD"},
                "positions": [
                    {
                        "symbol": "IBM",
                        "broker": "Recorded Price Path Broker",
                        "quantity": POSITION_QUANTITY,
                        "market_value": str(STALE_MARKET_VALUE_USD),
                        "currency": "USD",
                    }
                ],
            },
        },
    )
    assert import_response.status_code == 200, import_response.text
    assert import_response.json()["parsed_positions"] == 1

    report_response = await client.get(f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD")
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()

    # The recorded provider observations must have been parsed and persisted
    # EXACTLY (Decimal, declared quantization) by the report-time sync.
    fx_row = (
        await db.execute(
            select(FxRate).where(
                FxRate.base_currency == "USD",
                FxRate.quote_currency == "SGD",
                FxRate.rate_date == AS_OF,
            )
        )
    ).scalar_one()
    assert fx_row.rate == EXPECTED_USD_SGD_RATE
    assert fx_row.source == "yahoo_finance"

    price_row = (
        await db.execute(
            select(StockPrice).where(
                StockPrice.symbol == "IBM",
                StockPrice.price_date == AS_OF,
            )
        )
    ).scalar_one()
    assert price_row.price == EXPECTED_IBM_CLOSE

    # The CONVERTED value: the freshly synced price replaces the stale
    # imported snapshot, and the SGD report carries the exact converted
    # amount. total_assets is only this position for a fresh user.
    assert money_amount(report["total_assets"]) == EXPECTED_POSITION_VALUE_SGD, (
        f"balance sheet must carry the exact converted value "
        f"{EXPECTED_POSITION_VALUE_SGD} SGD "
        f"(2 x {EXPECTED_IBM_CLOSE} USD x {EXPECTED_USD_SGD_RATE}), "
        f"got {report['total_assets']}"
    )
    assert report["is_balanced"] is True
    assert money_amount(report["total_assets"]) > money_amount(STALE_MARKET_VALUE_USD), (
        "stale imported snapshot was never repriced"
    )

    holdings_response = await client.get(f"/portfolio/holdings?as_of_date={AS_OF.isoformat()}")
    assert holdings_response.status_code == 200, holdings_response.text
    holdings = holdings_response.json()["items"]
    ibm_holding = next((item for item in holdings if item["asset_identifier"] == "IBM"), None)
    assert ibm_holding is not None, holdings
    # Holdings report in the BASE currency (converted_value; native currency
    # kept separately) — the holding's SGD value must agree EXACTLY with the
    # balance sheet's SGD value, and the currency labels must say so (the
    # 2026-06-26 staging round was exactly cross-surface value/currency
    # disagreement).
    assert money_amount(ibm_holding["market_value"]) == EXPECTED_POSITION_VALUE_SGD
    assert ibm_holding["currency"] == "SGD"
    assert ibm_holding["native_currency"] == "USD"


def test_recorded_payloads_carry_the_pinned_closes() -> None:
    """AC-pricing.marketdata.13: the committed recordings really contain the
    closes the oracle constants were derived from (oracle self-consistency —
    a re-recorded fixture cannot silently shift the expected values)."""
    usdsgd = json.loads((FIXTURES / RECORDED_PAYLOADS["USDSGD=X"]).read_text(encoding="utf-8"))
    ibm = json.loads((FIXTURES / RECORDED_PAYLOADS["IBM"]).read_text(encoding="utf-8"))

    def close_on(payload: dict, target: date) -> Decimal:
        result = payload["chart"]["result"][0]
        for ts, close in zip(
            result["timestamp"],
            result["indicators"]["quote"][0]["close"],
            strict=False,
        ):
            observed = datetime.fromtimestamp(int(ts), UTC).date()
            if observed == target and close is not None:
                return Decimal(str(close))
        raise AssertionError(f"no close for {target} in recorded payload")

    assert close_on(usdsgd, AS_OF).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) == (EXPECTED_USD_SGD_RATE)
    assert close_on(ibm, AS_OF).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) == EXPECTED_IBM_CLOSE
    assert (
        POSITION_QUANTITY == "2"
        and (Decimal(POSITION_QUANTITY) * EXPECTED_IBM_CLOSE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        == EXPECTED_POSITION_VALUE_USD
    )
    assert (Decimal(POSITION_QUANTITY) * EXPECTED_IBM_CLOSE * EXPECTED_USD_SGD_RATE).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ) == EXPECTED_POSITION_VALUE_SGD
