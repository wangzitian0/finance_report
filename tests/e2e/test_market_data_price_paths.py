from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from common.testing import money_amount

from tests.e2e._journey_helpers import api_url, get_json, post_json
from tests.e2e.conftest import AuthState

MARKET_DATA_E2E_DATE = date.fromisoformat(
    os.getenv("MARKET_DATA_E2E_DATE", "2024-06-03")
)
MARKET_DATA_PROVIDER_E2E_ENABLED = os.getenv(
    "RUN_MARKET_DATA_PROVIDER_E2E", ""
).lower() in {"1", "true", "yes"}
MARKET_DATA_E2E_SYMBOL_CANDIDATES = tuple(
    s.strip().upper()
    for s in os.getenv(
        "MARKET_DATA_E2E_SYMBOL_CANDIDATES",
        "IBM,ORCL,INTC,CSCO,KO,PEP,WMT,DIS,V,MA,ADBE,CRM",
    ).split(",")
    if s.strip()
)
STALE_BROKERAGE_MARKET_VALUE = Decimal("20.00")


async def _market_data_status_by_scope(
    client: httpx.AsyncClient, *, symbols: tuple[str, ...]
) -> dict[tuple[str, str], dict]:
    params = [("pairs", "USD/SGD"), *(("symbols", s) for s in symbols)]
    resp = await client.get(api_url("/pricing/market-data/status"), params=params)
    assert resp.status_code == 200, (
        f"market data status failed: {resp.status_code} {resp.text}"
    )
    return {(item["kind"], item["scope"]): item for item in resp.json()}


def _select_stale_or_first_symbol(status_by_scope: dict[tuple[str, str], dict]) -> str:
    return next(
        (
            s
            for s in MARKET_DATA_E2E_SYMBOL_CANDIDATES
            if not (st := status_by_scope.get(("stock", s))) or not st["fresh"]
        ),
        MARKET_DATA_E2E_SYMBOL_CANDIDATES[0],
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.skipif(
    not MARKET_DATA_PROVIDER_E2E_ENABLED,
    reason="RUN_MARKET_DATA_PROVIDER_E2E is not enabled",
)
async def test_market_data_provider_sync_feeds_fx_and_stock_price_paths(
    shared_auth_state: AuthState,
) -> None:
    headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        symbol = _select_stale_or_first_symbol(
            await _market_data_status_by_scope(
                client, symbols=MARKET_DATA_E2E_SYMBOL_CANDIDATES
            )
        )
        broker_name = f"Market Data User E2E {symbol}"
        imp = await post_json(
            client,
            "/portfolio/brokerage-imports",
            json={
                "filename": f"market-data-user-e2e-{symbol.lower()}.json",
                "source_document_id": f"market-data-user-e2e-{shared_auth_state.user_id}-{uuid.uuid4()}",
                "payload": {
                    "institution": broker_name,
                    "statement": {
                        "period_end": MARKET_DATA_E2E_DATE.isoformat(),
                        "currency": "USD",
                    },
                    "positions": [
                        {
                            "symbol": symbol,
                            "broker": broker_name,
                            "quantity": "2",
                            "market_value": str(STALE_BROKERAGE_MARKET_VALUE),
                            "currency": "USD",
                        }
                    ],
                },
            },
            expected_status=(200,),
            label="brokerage import",
        )
        assert imp["parsed_positions"] == 1
        report = await get_json(
            client,
            f"/reports/balance-sheet?as_of_date={MARKET_DATA_E2E_DATE.isoformat()}&currency=SGD",
        )
        assert (
            report["is_balanced"] is True
            and money_amount(report["total_assets"]) > STALE_BROKERAGE_MARKET_VALUE
        )

        after_status = await _market_data_status_by_scope(client, symbols=(symbol,))
        stock_status, fx_status = (
            after_status.get(("stock", symbol)),
            after_status.get(("fx", "USD/SGD")),
        )
        assert stock_status is not None and fx_status is not None
        assert stock_status["fresh"] is True and fx_status["fresh"] is True
        assert (
            stock_status["last_observation_date"] is not None
            and fx_status["last_observation_date"] is not None
        )

        holdings = (
            await get_json(
                client,
                f"/portfolio/holdings?as_of_date={MARKET_DATA_E2E_DATE.isoformat()}",
            )
        )["items"]
        selected = next(
            (item for item in holdings if item["asset_identifier"] == symbol), None
        )
        assert (
            selected is not None
            and money_amount(selected["market_value"]) > STALE_BROKERAGE_MARKET_VALUE
        )
        assert [
            ln
            for ln in report.get("assets", [])
            if isinstance(ln, dict)
            and broker_name.lower() in str(ln.get("name", "")).lower()
            and "market valuation adjustment" in str(ln.get("name", "")).lower()
        ]
