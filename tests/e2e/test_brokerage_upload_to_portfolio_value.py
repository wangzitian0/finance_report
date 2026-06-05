"""
Tier 3 Browser/API E2E: Multi-brokerage upload to latest portfolio value.

Issue #404 / AC8.13.10:
Upload multiple brokerage PDFs through the configured real OCR path, import
positions from the parsed statements, and verify the latest portfolio value is
visible through product APIs.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from conftest import fail_or_skip_ai_ocr_gate
from playwright.async_api import Page

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _get_pdf_path(source: str) -> Path:
    from datetime import datetime

    root = Path(__file__).resolve().parents[2]
    source_dir = root / "tools" / "_lib" / "pdf_fixtures" / "output" / source
    yymm = datetime.now().strftime("%y%m")
    prebuilt = source_dir / f"test_{source}_{yymm}.pdf"
    if prebuilt.exists():
        return prebuilt
    if source_dir.exists():
        pdfs = sorted(source_dir.glob(f"test_{source}_*.pdf"))
        if pdfs:
            return pdfs[-1]

    script = root / "tools" / "generate_pdf_fixtures.py"
    result = subprocess.run(
        [sys.executable, str(script), "--source", source],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"PDF fixture generation failed for {source}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    pdfs = sorted(source_dir.glob(f"test_{source}_*.pdf")) if source_dir.exists() else []
    if not pdfs:
        pytest.skip(f"PDF generation for {source} produced no files in {source_dir}")
    return pdfs[-1]


def _unique_pdf_copy(src: Path) -> Path:
    suffix = int(time.time() * 1000) % 1_000_000
    tmp = Path(tempfile.mkdtemp())
    dest = tmp / f"{src.stem}_{suffix}{src.suffix}"
    shutil.copy2(src, dest)
    with open(dest, "ab") as f:
        f.write(f"\n%% E2E test run {uuid.uuid4()}\n".encode())
    return dest


async def _default_image_model(client: httpx.AsyncClient) -> str:
    response = await client.get(_api_url("/ai/models?modality=image"))
    assert response.status_code == 200, f"model catalog request failed: {response.status_code} {response.text}"
    payload = response.json()
    return payload.get("default_model") or payload["models"][0]["id"]


async def _upload_brokerage_pdf(
    client: httpx.AsyncClient,
    *,
    source: str,
    institution: str,
    model: str,
) -> str:
    pdf_path = _unique_pdf_copy(_get_pdf_path(source))
    with pdf_path.open("rb") as fh:
        response = await client.post(
            _api_url("/statements/upload"),
            data={"institution": institution, "model": model},
            files={"file": (pdf_path.name, fh, "application/pdf")},
        )
    assert response.status_code in (200, 201, 202), f"{source} upload failed: {response.status_code} {response.text}"
    statement_id = response.json().get("id")
    assert statement_id, f"{source} upload response missing id: {response.text}"
    return str(statement_id)


def _transaction_count(payload: dict | None) -> int | None:
    if not payload:
        return None
    transactions = payload.get("transactions")
    if isinstance(transactions, list):
        return len(transactions)
    return None


def _statement_poll_failure_message(statement_id: str, last_payload: dict | None) -> str:
    if not last_payload:
        return (
            f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; no poll payload was returned"
        )

    status = last_payload.get("status")
    progress = last_payload.get("parsing_progress")
    tx_count = _transaction_count(last_payload)
    validation_error = last_payload.get("validation_error")
    balance_validated = last_payload.get("balance_validated")

    if status in {"uploaded", "parsing"} and progress == 100 and tx_count and tx_count > 0:
        reason = "internal state-transition failure after OCR extraction"
    elif progress == 100 and tx_count == 0:
        reason = "provider parsing completed without importable transactions"
    elif status in {"uploaded", "parsing"}:
        reason = "provider parsing did not complete before timeout"
    else:
        reason = f"unexpected statement status {status!r}"

    return (
        f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; "
        f"{reason}; status={status!r}; parsing_progress={progress!r}; "
        f"transactions={tx_count!r}; balance_validated={balance_validated!r}; "
        f"validation_error={validation_error!r}"
    )


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _balance_sheet_asset_lines(balance_sheet: dict) -> list[dict]:
    assets = balance_sheet.get("assets")
    assert isinstance(assets, list), f"balance sheet missing asset lines: {balance_sheet}"
    return [line for line in assets if isinstance(line, dict)]


def _market_valuation_lines(balance_sheet: dict) -> list[dict]:
    return [
        line
        for line in _balance_sheet_asset_lines(balance_sheet)
        if "market valuation adjustment" in str(line.get("name", "")).lower()
    ]


def _line_total(lines: list[dict]) -> Decimal:
    return sum((_money(line.get("amount", "0")) for line in lines), Decimal("0.00")).quantize(Decimal("0.01"))


def _portfolio_valuation_failure_message(
    *,
    holdings: list[dict],
    total_market_value: Decimal,
    imported_positions: Decimal,
    balance_sheet: dict,
) -> str:
    asset_lines = _balance_sheet_asset_lines(balance_sheet)
    valuation_lines = _market_valuation_lines(balance_sheet)
    valuation_total = _line_total(valuation_lines)
    non_portfolio_asset_total = _line_total([line for line in asset_lines if line not in valuation_lines])
    relevant_asset_lines = [
        {
            "name": line.get("name"),
            "amount": str(line.get("amount")),
        }
        for line in asset_lines
        if line in valuation_lines or _money(line.get("amount", "0")) < Decimal("0.00")
    ]

    return (
        "portfolio market valuation coverage failed; "
        f"imported_positions={imported_positions}; "
        f"holdings_count={len(holdings)}; "
        f"holdings_total_market_value={total_market_value}; "
        f"market_valuation_adjustment_total={valuation_total}; "
        f"non_portfolio_asset_total={non_portfolio_asset_total}; "
        f"total_assets={balance_sheet.get('total_assets')}; "
        f"net_worth_adjustment_gain_loss={balance_sheet.get('net_worth_adjustment_gain_loss')}; "
        f"relevant_asset_lines={relevant_asset_lines}"
    )


def _assert_portfolio_market_valuation_covered(
    *,
    holdings: list[dict],
    imported_positions: Decimal,
    balance_sheet: dict,
) -> None:
    total_market_value = sum((_money(item["market_value"]) for item in holdings), Decimal("0.00")).quantize(
        Decimal("0.01")
    )
    assert total_market_value > Decimal("0.00"), f"holdings have no market value: {holdings}"

    valuation_lines = _market_valuation_lines(balance_sheet)
    valuation_total = _line_total(valuation_lines)
    failure_message = _portfolio_valuation_failure_message(
        holdings=holdings,
        total_market_value=total_market_value,
        imported_positions=imported_positions,
        balance_sheet=balance_sheet,
    )

    assert valuation_lines, failure_message
    assert valuation_total >= total_market_value, failure_message
    assert _money(balance_sheet["net_worth_adjustment_gain_loss"]) > Decimal("0.00"), failure_message


async def _wait_for_parsed_statement(client: httpx.AsyncClient, statement_id: str) -> dict:
    deadline = asyncio.get_event_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_payload: dict | None = None
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(_api_url(f"/statements/{statement_id}"))
        assert response.status_code == 200, (
            f"statement poll failed for {statement_id}: {response.status_code} {response.text}"
        )
        last_payload = response.json()
        status = last_payload.get("status")
        if status == "rejected":
            fail_or_skip_ai_ocr_gate(
                f"brokerage OCR/import gate rejected statement {statement_id}: {last_payload.get('validation_error')}",
                statement=last_payload,
            )
        if status == "parsed":
            assert last_payload.get("transactions"), (
                f"parsed statement {statement_id} has no transactions: {last_payload}"
            )
            return last_payload
        await asyncio.sleep(5)

    pytest.fail(_statement_poll_failure_message(statement_id, last_payload))


def test_statement_poll_failure_message_flags_state_transition_stall() -> None:
    """EPIC-003 EPIC-008 EPIC-009.

    AC8.13.10/Issue #409: E2E timeout distinguishes parsed-data routing stalls.
    """
    message = _statement_poll_failure_message(
        "stmt-409",
        {
            "status": "uploaded",
            "parsing_progress": 100,
            "transactions": [{"id": "txn-1"}],
            "balance_validated": False,
            "validation_error": None,
        },
    )

    assert "internal state-transition failure after OCR extraction" in message
    assert "transactions=1" in message


def test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines() -> None:
    """EPIC-005 EPIC-008 EPIC-017.

    AC8.13.18/Issue #433: Gate checks portfolio valuation lines, not total assets.
    """
    holdings = [{"market_value": "324980.5000000"}]
    balance_sheet = {
        "assets": [
            {"name": "Bank - Main", "amount": "-578.78"},
            {"name": "Futu market valuation adjustment", "amount": "323730.00"},
            {"name": "Moomoo market valuation adjustment", "amount": "1250.50"},
        ],
        "total_assets": "324401.72",
        "net_worth_adjustment_gain_loss": "324980.50",
    }

    _assert_portfolio_market_valuation_covered(
        holdings=holdings,
        imported_positions=Decimal("2"),
        balance_sheet=balance_sheet,
    )


def test_portfolio_valuation_gate_failure_diagnostics_are_actionable() -> None:
    """EPIC-005 EPIC-008 EPIC-017.

    AC8.13.19/Issue #433: Gate failure messages expose valuation and non-portfolio totals.
    """
    holdings = [{"market_value": "100.00"}]
    balance_sheet = {
        "assets": [
            {"name": "Bank - Main", "amount": "-10.00"},
            {"name": "Moomoo market valuation adjustment", "amount": "20.00"},
        ],
        "total_assets": "10.00",
        "net_worth_adjustment_gain_loss": "20.00",
    }

    message = _portfolio_valuation_failure_message(
        holdings=holdings,
        total_market_value=Decimal("100.00"),
        imported_positions=Decimal("1"),
        balance_sheet=balance_sheet,
    )

    assert "imported_positions=1" in message
    assert "holdings_total_market_value=100.00" in message
    assert "market_valuation_adjustment_total=20.00" in message
    assert "non_portfolio_asset_total=-10.00" in message
    assert "Moomoo market valuation adjustment" in message
    assert "Bank - Main" in message


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-003 EPIC-005 EPIC-008 EPIC-009 EPIC-017.

    AC8.13.10: two brokerage PDFs -> real OCR -> positions -> balance sheet value.
    """
    access_token = await authenticated_page_unique.evaluate(
        "() => window.localStorage.getItem('finance_access_token')"
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(headers=headers, verify=False, timeout=120.0) as client:
        model = await _default_image_model(client)
        uploads = [
            ("moomoo", "Moomoo E2E Portfolio"),
            ("futu", "Futu E2E Portfolio"),
        ]

        statement_ids = []
        for source, institution in uploads:
            statement_ids.append(
                await _upload_brokerage_pdf(
                    client,
                    source=source,
                    institution=institution,
                    model=model,
                )
            )

        parsed_statements = [await _wait_for_parsed_statement(client, statement_id) for statement_id in statement_ids]
        assert len(parsed_statements) == 2

        imported_positions = Decimal("0")
        for parsed_statement in parsed_statements:
            response = await client.post(_api_url(f"/statements/{parsed_statement['id']}/brokerage/import"))
            assert response.status_code == 200, (
                f"brokerage import failed for {parsed_statement['id']}: {response.status_code} {response.text}"
            )
            payload = response.json()
            assert payload["parsed_positions"] > 0, f"no positions imported for {parsed_statement['id']}: {payload}"
            imported_positions += Decimal(str(payload["parsed_positions"]))

        holdings_response = await client.get(_api_url("/portfolio/holdings"))
        assert holdings_response.status_code == 200, (
            f"holdings check failed: {holdings_response.status_code} {holdings_response.text}"
        )
        holdings = holdings_response.json()
        assert len(holdings) >= int(imported_positions), f"missing imported holdings: {holdings}"

        balance_response = await client.get(_api_url(f"/reports/balance-sheet?as_of_date={date.today().isoformat()}"))
        assert balance_response.status_code == 200, (
            f"balance sheet check failed: {balance_response.status_code} {balance_response.text}"
        )
        balance_sheet = balance_response.json()
        _assert_portfolio_market_valuation_covered(
            holdings=holdings,
            imported_positions=imported_positions,
            balance_sheet=balance_sheet,
        )
