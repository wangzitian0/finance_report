"""Provider-backed market data E2E paths for lazy FX and stock prices."""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest

from conftest import AuthState

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
MARKET_DATA_E2E_DATE = date.fromisoformat(
    os.getenv("MARKET_DATA_E2E_DATE", "2024-06-03")
)
MARKET_DATA_PROVIDER_E2E_ENABLED = os.getenv(
    "RUN_MARKET_DATA_PROVIDER_E2E", ""
).lower() in {"1", "true", "yes"}
MARKET_DATA_E2E_SYMBOL_CANDIDATES = tuple(
    symbol.strip().upper()
    for symbol in os.getenv(
        "MARKET_DATA_E2E_SYMBOL_CANDIDATES",
        "IBM,ORCL,INTC,CSCO,KO,PEP,WMT,DIS,V,MA,ADBE,CRM",
    ).split(",")
    if symbol.strip()
)
STALE_BROKERAGE_MARKET_VALUE = Decimal("20.00")


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def _market_data_status_by_scope(
    client: httpx.AsyncClient,
    *,
    symbols: tuple[str, ...],
) -> dict[tuple[str, str], dict]:
    params: list[tuple[str, str]] = [("pairs", "USD/SGD")]
    params.extend(("symbols", symbol) for symbol in symbols)
    response = await client.get(_api_url("/market-data/status"), params=params)
    assert response.status_code == 200, (
        f"market data status failed: {response.status_code} {response.text}"
    )
    return {(item["kind"], item["scope"]): item for item in response.json()}


def _select_stale_or_first_symbol(status_by_scope: dict[tuple[str, str], dict]) -> str:
    for symbol in MARKET_DATA_E2E_SYMBOL_CANDIDATES:
        status = status_by_scope.get(("stock", symbol))
        if status is None or not status["fresh"]:
            return symbol
    return MARKET_DATA_E2E_SYMBOL_CANDIDATES[0]


def _market_valuation_lines(report: dict, broker_name: str) -> list[dict]:
    return [
        line
        for line in report.get("assets", [])
        if isinstance(line, dict)
        and broker_name.lower() in str(line.get("name", "")).lower()
        and "market valuation adjustment" in str(line.get("name", "")).lower()
    ]


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
    """EPIC-005 EPIC-008 EPIC-011 EPIC-017.

    AC11.10.7 AC11.10.11: Reports auto-refresh provider FX and stock data
    from a user path.
    """
    headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        before_status = await _market_data_status_by_scope(
            client,
            symbols=MARKET_DATA_E2E_SYMBOL_CANDIDATES,
        )
        symbol = _select_stale_or_first_symbol(before_status)
        broker_name = f"Market Data User E2E {symbol}"
        import_response = await client.post(
            _api_url("/portfolio/brokerage/import"),
            json={
                "filename": f"market-data-user-e2e-{symbol.lower()}.json",
                "source_document_id": (
                    f"market-data-user-e2e-{shared_auth_state.user_id}-{uuid.uuid4()}"
                ),
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
        )
        assert import_response.status_code == 200, (
            f"brokerage import failed: {import_response.status_code} {import_response.text}"
        )
        assert import_response.json()["parsed_positions"] == 1

        report_response = await client.get(
            _api_url(
                f"/reports/balance-sheet?as_of_date={MARKET_DATA_E2E_DATE.isoformat()}&currency=SGD"
            )
        )
        assert report_response.status_code == 200, (
            f"balance sheet failed through report-time market data refresh: "
            f"{report_response.status_code} {report_response.text}"
        )
        report = report_response.json()
        assert report["is_balanced"] is True
        assert _money(report["total_assets"]) > STALE_BROKERAGE_MARKET_VALUE, report

        after_status = await _market_data_status_by_scope(client, symbols=(symbol,))
        stock_status = after_status.get(("stock", symbol))
        fx_status = after_status.get(("fx", "USD/SGD"))
        assert stock_status is not None, after_status
        assert fx_status is not None, after_status
        assert stock_status["fresh"] is True, stock_status
        assert fx_status["fresh"] is True, fx_status
        assert stock_status["last_observation_date"] is not None, stock_status
        assert fx_status["last_observation_date"] is not None, fx_status

        holdings_response = await client.get(
            _api_url(
                f"/portfolio/holdings?as_of_date={MARKET_DATA_E2E_DATE.isoformat()}"
            )
        )
        assert holdings_response.status_code == 200, (
            f"holdings failed: {holdings_response.status_code} {holdings_response.text}"
        )
        holdings = holdings_response.json()
        selected_holding = next(
            (item for item in holdings if item["asset_identifier"] == symbol), None
        )
        assert selected_holding is not None, f"{symbol} holding missing: {holdings}"
        assert _money(selected_holding["market_value"]) > STALE_BROKERAGE_MARKET_VALUE, (
            f"synced stock price did not replace stale brokerage snapshot: {selected_holding}"
        )

        valuation_lines = _market_valuation_lines(report, broker_name)
        assert valuation_lines, (
            f"balance sheet did not expose the refreshed brokerage valuation line; "
            f"broker={broker_name}; report={report}"
        )
