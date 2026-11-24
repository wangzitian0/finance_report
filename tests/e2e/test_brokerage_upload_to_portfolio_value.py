from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
from common.testing import money_amount
from playwright.async_api import Page

from tests.e2e._journey_helpers import (
    PARSING_TIMEOUT_MS,
    auth_headers,
    get_json,
    import_brokerage_and_holdings,
    line_total,
    unique_pdf_copy,
    upload_statement,
    wait_for_statement,
)
from tests.e2e.pdf_fixture_paths import generated_pdf_path


def _balance_sheet_asset_lines(balance_sheet: dict) -> list[dict]:
    assets = balance_sheet.get("assets")
    assert isinstance(assets, list), (
        f"balance sheet missing asset lines: {balance_sheet}"
    )
    return [line for line in assets if isinstance(line, dict)]


def _market_valuation_lines(balance_sheet: dict) -> list[dict]:
    return [
        ln
        for ln in _balance_sheet_asset_lines(balance_sheet)
        if "market valuation adjustment" in str(ln.get("name", "")).lower()
    ]


def _statement_poll_failure_message(
    statement_id: str, last_payload: dict | None
) -> str:
    if not last_payload:
        return f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; no poll payload was returned"
    status, progress, txns = (
        last_payload.get("status"),
        last_payload.get("parsing_progress"),
        last_payload.get("transactions"),
    )
    tx_count = len(txns) if isinstance(txns, list) else None
    reason = (
        "internal state-transition failure after OCR extraction"
        if status in {"uploaded", "parsing"}
        and progress == 100
        and tx_count
        and tx_count > 0
        else "provider parsing completed without importable transactions"
        if progress == 100 and tx_count == 0
        else "provider parsing did not complete before timeout"
        if status in {"uploaded", "parsing"}
        else f"unexpected statement status {status!r}"
    )
    return f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; {reason}; status={status!r}; parsing_progress={progress!r}; transactions={tx_count!r}; balance_validated={last_payload.get('balance_validated')!r}; validation_error={last_payload.get('validation_error')!r}"


def _portfolio_valuation_failure_message(
    *,
    holdings: list[dict],
    total_market_value: Decimal,
    imported_positions: Decimal,
    balance_sheet: dict,
) -> str:
    asset_lines, val_lines = (
        _balance_sheet_asset_lines(balance_sheet),
        _market_valuation_lines(balance_sheet),
    )
    relevant = [
        {"name": ln.get("name"), "amount": str(ln.get("amount"))}
        for ln in asset_lines
        if ln in val_lines or money_amount(ln.get("amount", "0")) < Decimal("0.00")
    ]
    return f"portfolio market valuation coverage failed; imported_positions={imported_positions}; holdings_count={len(holdings)}; holdings_total_market_value={total_market_value}; market_valuation_adjustment_total={line_total(val_lines)}; non_portfolio_asset_total={line_total([ln for ln in asset_lines if ln not in val_lines])}; total_assets={balance_sheet.get('total_assets')}; net_worth_adjustment_gain_loss={balance_sheet.get('net_worth_adjustment_gain_loss')}; relevant_asset_lines={relevant}"


def _assert_portfolio_market_valuation_covered(
    *, holdings: list[dict], imported_positions: Decimal, balance_sheet: dict
) -> None:
    total_mv = money_amount(
        sum((money_amount(item["market_value"]) for item in holdings), Decimal("0.00"))
    )
    assert total_mv > Decimal("0.00")
    val_lines = _market_valuation_lines(balance_sheet)
    msg = _portfolio_valuation_failure_message(
        holdings=holdings,
        total_market_value=total_mv,
        imported_positions=imported_positions,
        balance_sheet=balance_sheet,
    )
    assert (
        val_lines
        and line_total(val_lines) >= total_mv
        and money_amount(balance_sheet["net_worth_adjustment_gain_loss"])
        > Decimal("0.00")
    ), msg


def test_statement_poll_failure_message_flags_state_transition_stall() -> None:
    msg = _statement_poll_failure_message(
        "stmt-409",
        {
            "status": "uploaded",
            "parsing_progress": 100,
            "transactions": [{"id": "txn-1"}],
            "balance_validated": False,
            "validation_error": None,
        },
    )
    assert (
        "internal state-transition failure after OCR extraction" in msg
        and "transactions=1" in msg
    )


def test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines() -> None:
    _assert_portfolio_market_valuation_covered(
        holdings=[{"market_value": "324980.5000000"}],
        imported_positions=Decimal("2"),
        balance_sheet={
            "assets": [
                {"name": "Bank - Main", "amount": "-578.78"},
                {"name": "Futu market valuation adjustment", "amount": "323730.00"},
                {"name": "Moomoo market valuation adjustment", "amount": "1250.50"},
            ],
            "total_assets": "324401.72",
            "net_worth_adjustment_gain_loss": "324980.50",
        },
    )


def test_portfolio_valuation_gate_failure_diagnostics_are_actionable() -> None:
    msg = _portfolio_valuation_failure_message(
        holdings=[{"market_value": "100.00"}],
        total_market_value=Decimal("100.00"),
        imported_positions=Decimal("1"),
        balance_sheet={
            "assets": [
                {"name": "Bank - Main", "amount": "-10.00"},
                {"name": "Moomoo market valuation adjustment", "amount": "20.00"},
            ],
            "total_assets": "10.00",
            "net_worth_adjustment_gain_loss": "20.00",
        },
    )
    assert all(
        t in msg
        for t in (
            "imported_positions=1",
            "holdings_total_market_value=100.00",
            "market_valuation_adjustment_total=20.00",
            "non_portfolio_asset_total=-10.00",
            "Moomoo market valuation adjustment",
            "Bank - Main",
        )
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value(
    authenticated_page_unique: Page,
) -> None:
    async with httpx.AsyncClient(
        headers=await auth_headers(authenticated_page_unique),
        verify=False,
        timeout=120.0,
    ) as client:
        statement_ids = [
            await upload_statement(
                client,
                filename=(p := unique_pdf_copy(generated_pdf_path(src))).name,
                content=p.read_bytes(),
                content_type="application/pdf",
                institution=inst,
                label=src,
            )
            for src, inst in (
                ("moomoo", "Moomoo E2E Portfolio"),
                ("futu", "Futu E2E Portfolio"),
            )
        ]
        parsed = [
            await wait_for_statement(
                client,
                sid,
                poll_seconds=5,
                target_statuses=("parsed",),
                gate_name="brokerage OCR/import",
                timeout_formatter=_statement_poll_failure_message,
            )
            for sid in statement_ids
        ]
        imported_positions, holdings = Decimal("0"), []
        for st in parsed:
            count, holdings = await import_brokerage_and_holdings(client, st["id"])
            imported_positions += Decimal(str(count))
        assert len(holdings) >= int(imported_positions) and all(
            money_amount(h["market_value"]) > Decimal("0.00")
            and Decimal(str(h["quantity"])) > Decimal("0")
            for h in holdings
        )
        # A statement import records no purchase: cost and profit are empty, not the market value (#2920).
        assert {(h["cost_basis"], h["unrealized_pnl"]) for h in holdings} == {(None, None)}
        _assert_portfolio_market_valuation_covered(
            holdings=holdings,
            imported_positions=imported_positions,
            balance_sheet=await get_json(
                client, f"/reports/balance-sheet?as_of_date={date.today().isoformat()}"
            ),
        )
