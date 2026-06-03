"""
Tier 3 Browser/API E2E: four-asset as-of net worth golden path.

Issue #444:
Fresh user uploads deterministic bank statement data, imports a brokerage PDF,
creates manual property, mortgage, and ESOP valuation snapshots, then verifies
exact as-of net worth through reports and dashboard totals.
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
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx
import pytest
from conftest import fail_or_skip_ai_ocr_gate
from playwright.async_api import Page, expect

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))

BANK_INSTITUTION = "Four Asset E2E Bank"
BANK_CASH = Decimal("2500.00")
PROPERTY_VALUE = Decimal("1200000.00")
MORTGAGE_BALANCE = Decimal("650000.00")
ESOP_VALUE = Decimal("42000.00")


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _dashboard_amount(amount: Decimal) -> str:
    rounded = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(rounded):,}"


def _report_amount(amount: Decimal) -> str:
    rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:,.2f}"


def _write_bank_fixture(tmp_path: Path, report_date: date) -> Path:
    path = tmp_path / "four_asset_bank_statement.csv"
    path.write_text(
        "\n".join(
            [
                "Date,Description,Amount",
                f"{report_date.isoformat()},Four Asset Salary,3000.00",
                f"{report_date.isoformat()},Four Asset Rent,-500.00",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


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
        pytest.skip(
            f"PDF fixture generation failed for {source}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    pdfs = (
        sorted(source_dir.glob(f"test_{source}_*.pdf")) if source_dir.exists() else []
    )
    if not pdfs:
        pytest.skip(f"PDF generation for {source} produced no files in {source_dir}")
    return pdfs[-1]


def _unique_pdf_copy(src: Path) -> Path:
    suffix = int(time.time() * 1000) % 1_000_000
    tmp = Path(tempfile.mkdtemp())
    dest = tmp / f"{src.stem}_{suffix}{src.suffix}"
    shutil.copy2(src, dest)
    with dest.open("ab") as fh:
        fh.write(f"\n%% E2E test run {uuid.uuid4()}\n".encode())
    return dest


async def _auth_headers(page: Page) -> dict[str, str]:
    token = await page.evaluate(
        "() => window.localStorage.getItem('finance_access_token')"
    )
    assert token, "Missing finance_access_token in localStorage"
    return {"Authorization": f"Bearer {token}"}


async def _default_image_model(client: httpx.AsyncClient) -> str:
    response = await client.get(_api_url("/ai/models?modality=image"))
    assert response.status_code == 200, (
        f"model catalog request failed: {response.status_code} {response.text}"
    )
    payload = response.json()
    return payload.get("default_model") or payload["models"][0]["id"]


async def _upload_bank_csv(client: httpx.AsyncClient, fixture_path: Path) -> str:
    with fixture_path.open("rb") as fh:
        response = await client.post(
            _api_url("/statements/upload"),
            data={"institution": BANK_INSTITUTION},
            files={"file": (fixture_path.name, fh, "text/csv")},
        )
    assert response.status_code in (200, 201, 202), (
        f"bank upload failed: {response.status_code} {response.text}"
    )
    statement_id = response.json().get("id")
    assert statement_id, f"bank upload response missing id: {response.text}"
    return str(statement_id)


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
    assert response.status_code in (200, 201, 202), (
        f"{source} upload failed: {response.status_code} {response.text}"
    )
    statement_id = response.json().get("id")
    assert statement_id, f"{source} upload response missing id: {response.text}"
    return str(statement_id)


def _transaction_count(payload: dict | None) -> int | None:
    transactions = payload.get("transactions") if payload else None
    return len(transactions) if isinstance(transactions, list) else None


def _statement_timeout_message(statement_id: str, last_payload: dict | None) -> str:
    if not last_payload:
        return f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms"
    return (
        f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; "
        f"status={last_payload.get('status')!r}; "
        f"parsing_progress={last_payload.get('parsing_progress')!r}; "
        f"transactions={_transaction_count(last_payload)!r}; "
        f"balance_validated={last_payload.get('balance_validated')!r}; "
        f"validation_error={last_payload.get('validation_error')!r}"
    )


async def _wait_for_parsed_statement(
    client: httpx.AsyncClient,
    statement_id: str,
    *,
    gate_name: str,
) -> dict:
    deadline = asyncio.get_running_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_payload: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(_api_url(f"/statements/{statement_id}"))
        assert response.status_code == 200, (
            f"{gate_name} statement poll failed for {statement_id}: {response.status_code} {response.text}"
        )
        last_payload = response.json()
        status = last_payload.get("status")
        if status == "rejected":
            fail_or_skip_ai_ocr_gate(
                f"{gate_name} gate rejected statement {statement_id}: {last_payload.get('validation_error')}",
                statement=last_payload,
            )
        if status == "parsed":
            assert last_payload.get("transactions"), (
                f"{gate_name} parsed statement {statement_id} has no transactions: {last_payload}"
            )
            return last_payload
        await asyncio.sleep(5)

    pytest.fail(_statement_timeout_message(statement_id, last_payload))


async def _create_manual_snapshot(
    client: httpx.AsyncClient,
    *,
    component_type: str,
    as_of_date: date,
    value: Decimal,
    source: str,
) -> dict:
    payload = {
        "component_type": component_type,
        "as_of_date": as_of_date.isoformat(),
        "value": str(value),
        "currency": "SGD",
        "source": source,
    }
    response = await client.post(_api_url("/assets/valuation-snapshots"), json=payload)
    assert response.status_code == 201, (
        f"manual valuation snapshot create failed for {component_type}: {response.status_code} {response.text}"
    )
    return response.json()


def _line_total(lines: list[dict]) -> Decimal:
    return sum(
        (_money(line.get("amount", "0")) for line in lines), Decimal("0.00")
    ).quantize(Decimal("0.01"))


def _lines_by_name(lines: list[dict], token: str) -> list[dict]:
    token_lower = token.lower()
    return [line for line in lines if token_lower in str(line.get("name", "")).lower()]


def _line_total_by_name(lines: list[dict], token: str) -> Decimal:
    matches = _lines_by_name(lines, token)
    assert matches, f"missing balance-sheet line containing {token!r}; lines={lines}"
    return _line_total(matches)


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_four_asset_as_of_net_worth_golden_path(
    authenticated_page_unique: Page,
    tmp_path: Path,
) -> None:
    """EPIC-005 EPIC-008 EPIC-011 EPIC-017.

    AC8.13.42 AC8.13.10 AC5.7.3 AC11.9.1 AC11.9.2 AC11.9.3 AC17.5.4:
    four assets produce exact as-of net worth.
    """
    page = authenticated_page_unique
    report_date = date.today()
    headers = await _auth_headers(page)

    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        bank_fixture = _write_bank_fixture(tmp_path, report_date)
        bank_statement_id = await _upload_bank_csv(client, bank_fixture)
        parsed_bank = await _wait_for_parsed_statement(
            client, bank_statement_id, gate_name="bank CSV"
        )
        assert len(parsed_bank.get("transactions") or []) == 2

        approve_response = await client.post(
            _api_url(f"/statements/{bank_statement_id}/review/approve"),
            json={"create_account_if_missing": True},
        )
        assert approve_response.status_code == 200, (
            f"bank stage 1 approve failed: {approve_response.status_code} {approve_response.text}"
        )
        approve_payload = approve_response.json()
        assert approve_payload["journal_entries_created"] == 2

        journal_response = await client.get(_api_url("/journal-entries?limit=6"))
        assert journal_response.status_code == 200, (
            f"journal entry check failed: {journal_response.status_code} {journal_response.text}"
        )
        journal_payload = journal_response.json()
        assert journal_payload["total"] == 2
        assert {item["status"].lower() for item in journal_payload["items"]} == {
            "posted"
        }
        assert {item["memo"] for item in journal_payload["items"]} == {
            "Four Asset Salary",
            "Four Asset Rent",
        }

        first_reconciliation = await client.post(
            _api_url("/reconciliation/run"),
            json={"statement_id": bank_statement_id},
        )
        assert first_reconciliation.status_code == 200, (
            f"first reconciliation failed: {first_reconciliation.status_code} {first_reconciliation.text}"
        )
        assert first_reconciliation.json() == {
            "matches_created": 2,
            "auto_accepted": 2,
            "pending_review": 0,
            "unmatched": 0,
        }

        second_reconciliation = await client.post(
            _api_url("/reconciliation/run"),
            json={"statement_id": bank_statement_id},
        )
        assert second_reconciliation.status_code == 200, (
            f"second reconciliation failed: {second_reconciliation.status_code} {second_reconciliation.text}"
        )
        assert second_reconciliation.json() == {
            "matches_created": 0,
            "auto_accepted": 0,
            "pending_review": 0,
            "unmatched": 0,
        }

        stage2_queue = await client.get(_api_url("/statements/stage2/queue"))
        assert stage2_queue.status_code == 200, (
            f"stage 2 queue check failed: {stage2_queue.status_code} {stage2_queue.text}"
        )
        stage2_payload = stage2_queue.json()
        assert stage2_payload["pending_matches"] == []
        assert stage2_payload["has_unresolved_checks"] is False

        model = await _default_image_model(client)
        brokerage_statement_id = await _upload_brokerage_pdf(
            client,
            source="moomoo",
            institution="Moomoo Four Asset E2E",
            model=model,
        )
        parsed_brokerage = await _wait_for_parsed_statement(
            client,
            brokerage_statement_id,
            gate_name="brokerage PDF",
        )
        import_response = await client.post(
            _api_url(f"/statements/{parsed_brokerage['id']}/brokerage/import")
        )
        assert import_response.status_code == 200, (
            f"brokerage import failed: {import_response.status_code} {import_response.text}"
        )
        import_payload = import_response.json()
        assert import_payload["parsed_positions"] > 0, (
            f"no brokerage positions imported: {import_payload}"
        )

        holdings_response = await client.get(_api_url("/portfolio/holdings"))
        assert holdings_response.status_code == 200, (
            f"holdings check failed: {holdings_response.status_code} {holdings_response.text}"
        )
        holdings = holdings_response.json()
        assert len(holdings) >= import_payload["parsed_positions"], (
            f"missing imported holdings: {holdings}"
        )
        brokerage_value = sum(
            (_money(item["market_value"]) for item in holdings), Decimal("0.00")
        ).quantize(Decimal("0.01"))
        assert brokerage_value > Decimal("0.00"), (
            f"brokerage holdings have no market value: {holdings}"
        )

        property_snapshot = await _create_manual_snapshot(
            client,
            component_type="property_value",
            as_of_date=report_date,
            value=PROPERTY_VALUE,
            source="Four Asset Condo",
        )
        mortgage_snapshot = await _create_manual_snapshot(
            client,
            component_type="mortgage_balance",
            as_of_date=report_date,
            value=MORTGAGE_BALANCE,
            source="Four Asset Mortgage",
        )
        esop_snapshot = await _create_manual_snapshot(
            client,
            component_type="esop",
            as_of_date=report_date,
            value=ESOP_VALUE,
            source="Four Asset ESOP",
        )
        assert property_snapshot["liquidity_class"] == "illiquid"
        assert mortgage_snapshot["liquidity_class"] == "liability"
        assert esop_snapshot["liquidity_class"] == "restricted"

        components_response = await client.get(
            _api_url(
                f"/assets/valuation-components?as_of_date={report_date.isoformat()}&include_restricted=true"
            )
        )
        assert components_response.status_code == 200, (
            f"valuation components check failed: {components_response.status_code} {components_response.text}"
        )
        components = components_response.json()
        assert _money(components["total_assets"]) == PROPERTY_VALUE + ESOP_VALUE
        assert _money(components["total_liabilities"]) == MORTGAGE_BALANCE
        assert (
            _money(components["net_worth_delta"])
            == PROPERTY_VALUE + ESOP_VALUE - MORTGAGE_BALANCE
        )

        balance_response = await client.get(
            _api_url(
                f"/reports/balance-sheet?as_of_date={report_date.isoformat()}&currency=SGD&include_restricted=true"
            )
        )
        assert balance_response.status_code == 200, (
            f"balance sheet check failed: {balance_response.status_code} {balance_response.text}"
        )
        balance_sheet = balance_response.json()
        asset_lines = [
            line for line in balance_sheet.get("assets", []) if isinstance(line, dict)
        ]
        liability_lines = [
            line
            for line in balance_sheet.get("liabilities", [])
            if isinstance(line, dict)
        ]
        market_lines = _lines_by_name(asset_lines, "market valuation adjustment")
        market_total = _line_total(market_lines)

        expected_assets = (
            BANK_CASH + brokerage_value + PROPERTY_VALUE + ESOP_VALUE
        ).quantize(Decimal("0.01"))
        expected_liabilities = MORTGAGE_BALANCE
        expected_net_worth = (expected_assets - expected_liabilities).quantize(
            Decimal("0.01")
        )
        expected_net_worth_adjustment = (
            brokerage_value + PROPERTY_VALUE + ESOP_VALUE - MORTGAGE_BALANCE
        ).quantize(Decimal("0.01"))

        assert _line_total_by_name(asset_lines, BANK_INSTITUTION) == BANK_CASH
        assert market_total == brokerage_value, (
            f"brokerage market value did not reach reporting exactly; holdings={holdings}; "
            f"market_lines={market_lines}; balance_sheet={balance_sheet}"
        )
        assert _line_total_by_name(asset_lines, "Four Asset Condo") == PROPERTY_VALUE
        assert _line_total_by_name(asset_lines, "Four Asset ESOP") == ESOP_VALUE
        assert (
            _line_total_by_name(liability_lines, "Four Asset Mortgage")
            == MORTGAGE_BALANCE
        )
        assert _money(balance_sheet["total_assets"]) == expected_assets
        assert _money(balance_sheet["total_liabilities"]) == expected_liabilities
        assert (
            _money(balance_sheet["total_assets"])
            - _money(balance_sheet["total_liabilities"])
            == expected_net_worth
        )
        assert (
            _money(balance_sheet["net_worth_adjustment_gain_loss"])
            == expected_net_worth_adjustment
        )
        assert _money(balance_sheet["equation_delta"]) == Decimal("0.00")
        assert balance_sheet["is_balanced"] is True

    await page.goto(_get_url("/dashboard"))
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Upload to report")).to_be_visible(
        timeout=10_000
    )
    await expect(page.get_by_label("Dashboard analytics")).to_be_visible(
        timeout=10_000
    )
    include_checkbox = page.get_by_label("Include restricted holdings")
    await expect(include_checkbox).to_be_visible(timeout=10_000)
    if not await include_checkbox.is_checked():
        await include_checkbox.check()

    await expect(
        page.locator(".card")
        .filter(has_text="Total Assets")
        .filter(has_text=_dashboard_amount(expected_assets))
    ).to_be_visible(timeout=15_000)
    await expect(
        page.locator(".card")
        .filter(has_text="Total Liabilities")
        .filter(has_text=_dashboard_amount(expected_liabilities))
    ).to_be_visible(timeout=15_000)
    await expect(
        page.locator(".card")
        .filter(has_text="Net Assets")
        .filter(has_text=_dashboard_amount(expected_net_worth))
    ).to_be_visible(timeout=15_000)

    await page.goto(
        _get_url(
            f"/reports/balance-sheet?as_of_date={report_date.isoformat()}&currency=SGD"
        )
    )
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=10_000
    )
    await expect(
        page.locator(".card").filter(has_text="Assets").filter(has_text="Total:")
    ).to_contain_text(
        _report_amount(expected_assets),
        timeout=15_000,
    )
    await expect(
        page.locator(".card").filter(has_text="Liabilities").filter(has_text="Total:")
    ).to_contain_text(
        _report_amount(expected_liabilities),
        timeout=15_000,
    )
