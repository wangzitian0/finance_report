"""
Tier 3 Browser/API E2E: personal financial report package proof.

Issue #565:
Fresh-user post-merge proof for one complete personal report package journey:
bank statement ingest, reconciliation idempotency, brokerage import,
manual valuation snapshots, report and traceability assertions, and report export.
"""

from __future__ import annotations

import asyncio
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from time import time
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest
from common.testing import money_amount
from common.testing.ac_proof import ac_proof
from conftest import fail_or_skip_ai_ocr_gate
from playwright.async_api import Page, expect
from tools._lib.fixtures.personal_report_package import REPRESENTATIVE_PACKAGE_FIXTURE

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))

PACKAGE_FIXTURE = REPRESENTATIVE_PACKAGE_FIXTURE
FIXTURE_PATH: Path = PACKAGE_FIXTURE.bank.csv_path
BANK_INSTITUTION = PACKAGE_FIXTURE.bank.institution
BROKERAGE_SOURCE = PACKAGE_FIXTURE.brokerage.source
BROKERAGE_INSTITUTION = PACKAGE_FIXTURE.brokerage.institution

PROPERTY_COMPONENT = PACKAGE_FIXTURE.component("property_value", "Family Home")
MORTGAGE_COMPONENT = PACKAGE_FIXTURE.component("mortgage_balance", "Home Loan")
ESOP_COMPONENT = PACKAGE_FIXTURE.component("esop", "ACME ESOP")
RSU_COMPONENT = PACKAGE_FIXTURE.component("rsu", "ACME RSU")
STOCK_OPTIONS_COMPONENT = PACKAGE_FIXTURE.component("stock_options", "ACME Options")

PROPERTY_VALUE = PROPERTY_COMPONENT.value
MORTGAGE_BALANCE = MORTGAGE_COMPONENT.value
ESOP_VALUE = ESOP_COMPONENT.value
RSU_VALUE = RSU_COMPONENT.value
STOCK_OPTIONS_VALUE = STOCK_OPTIONS_COMPONENT.value

PROPERTY_SOURCE = PROPERTY_COMPONENT.source
MORTGAGE_SOURCE = MORTGAGE_COMPONENT.source
ESOP_SOURCE = ESOP_COMPONENT.source
RSU_SOURCE = RSU_COMPONENT.source
STOCK_OPTIONS_SOURCE = STOCK_OPTIONS_COMPONENT.source
PROPERTY_NOTES = PROPERTY_COMPONENT.notes
MORTGAGE_NOTES = MORTGAGE_COMPONENT.notes
ESOP_NOTES = ESOP_COMPONENT.notes
RSU_NOTES = RSU_COMPONENT.notes
STOCK_OPTIONS_NOTES = STOCK_OPTIONS_COMPONENT.notes


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


async def _auth_headers(page: Page) -> dict[str, str]:
    cookies = await page.context.cookies(APP_URL)
    auth_cookie = next(
        (cookie for cookie in cookies if cookie["name"] == "finance_access_token"),
        None,
    )
    assert auth_cookie, "authenticated Playwright context is missing auth cookie"
    return {"Cookie": f"finance_access_token={auth_cookie['value']}"}


def _statement_timeout_message(statement_id: str, last_payload: dict | None) -> str:
    if not last_payload:
        return f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; no poll payload was returned"

    status = last_payload.get("status")
    parsing_progress = last_payload.get("parsing_progress")
    transactions = last_payload.get("transactions")
    tx_count = len(transactions) if isinstance(transactions, list) else None
    return (
        f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; "
        f"status={status!r}; parsing_progress={parsing_progress!r}; "
        f"transactions={tx_count!r}; balance_validated={last_payload.get('balance_validated')!r}; "
        f"validation_error={last_payload.get('validation_error')!r}"
    )


async def _wait_for_parsed_statement(
    client: httpx.AsyncClient,
    statement_id: str,
    *,
    gate_name: str,
    require_transactions: bool = True,
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
            if require_transactions:
                assert isinstance(last_payload.get("transactions"), list), (
                    f"parsed statement {statement_id} has no transactions payload"
                )
                assert last_payload["transactions"], (
                    f"parsed statement {statement_id} has empty transactions list"
                )
            return last_payload
        await asyncio.sleep(5)

    pytest.fail(_statement_timeout_message(statement_id, last_payload))


async def _default_image_model(client: httpx.AsyncClient) -> str:
    response = await client.get(_api_url("/llm/catalog?modality=image"))
    assert response.status_code == 200, (
        f"model catalog request failed: {response.status_code} {response.text}"
    )
    payload = response.json()
    return payload.get("default_model") or payload["models"][0]["id"]


def _get_pdf_path(source: str) -> Path:
    from datetime import datetime

    from common.testing.fixtures.pdf.generate_pdf_fixtures import default_output_dir

    root = Path(__file__).resolve().parents[2]
    source_dir = default_output_dir() / source
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
            f"PDF fixture generation failed for {source}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    pdfs = (
        sorted(source_dir.glob(f"test_{source}_*.pdf")) if source_dir.exists() else []
    )
    if not pdfs:
        pytest.skip(f"PDF generation for {source} produced no files in {source_dir}")
    return pdfs[-1]


def _unique_pdf_copy(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp())
    suffix = int(time() * 1000) % 1_000_000
    dest = tmp / f"{src.stem}_{suffix}{src.suffix}"
    shutil.copy2(src, dest)
    with dest.open("ab") as fh:
        fh.write(f"\n%% E2E test run {uuid4()}\n".encode())
    return dest


def _parse_csv_rows(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(content)))


def _assert_csv_total(content: str, section: str, expected: Decimal) -> None:
    rows = _parse_csv_rows(content)
    for row in rows:
        if row.get("section") == section:
            assert money_amount(row["amount"]) == expected, (
                f"CSV section {section} mismatch: expected {expected}, got {row['amount']}"
            )
            return
    pytest.fail(
        f"CSV export missing section {section}: sections={[row.get('section') for row in rows]}"
    )


def _assert_traceability(statement_rows: list[dict], journal_rows: list[dict]) -> None:
    txn_ids = {str(txn["id"]) for txn in statement_rows}
    matched = []
    for txn_id in txn_ids:
        related = [
            entry for entry in journal_rows if str(entry.get("source_id")) == txn_id
        ]
        assert related, f"no journal entry linked to statement transaction {txn_id}"
        assert {entry.get("status") for entry in related} <= {"posted", "reconciled"}, (
            f"statement-linked entries for transaction {txn_id} must be posted/reconciled: {related}"
        )
        statement_types = {str(entry.get("source_type")) for entry in related}
        assert statement_types.issubset(
            {
                "manual",
                "user_confirmed",
                "auto_matched",
                "auto_parsed",
                "bank_statement",
            }
        ), (
            f"statement-linked entries for {txn_id} have unexpected source_type: {statement_types}"
        )
        matched.extend(related)

    assert matched, "expected at least one statement-linked journal entry"


def _has_dynamic_traceability_identifiers(traceability: dict) -> bool:
    return any(
        anchor.get("identifiers")
        for line in traceability.get("lines", [])
        for anchor in (line.get("source_anchor", {}), line.get("ledger_anchor", {}))
    )


def _has_price_source_link(source_links: list[str]) -> bool:
    return any(source_link.startswith("price_source:") for source_link in source_links)


def _line_total(lines: list[dict], token: str | None = None) -> Decimal:
    filtered = (
        lines
        if token is None
        else [
            line for line in lines if token.lower() in str(line.get("name", "")).lower()
        ]
    )
    return sum((money_amount(line["amount"]) for line in filtered), Decimal("0.00"))


async def _upload_bank_csv(
    client: httpx.AsyncClient,
    fixture_path: Path,
    *,
    institution: str,
) -> str:
    with fixture_path.open("rb") as fh:
        response = await client.post(
            _api_url("/statements/upload"),
            data={"institution": institution},
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


async def _create_manual_snapshot(
    client: httpx.AsyncClient,
    *,
    component_type: str,
    as_of_date: date,
    value: Decimal,
    source: str,
    notes: str,
) -> dict:
    response = await client.post(
        _api_url("/assets/valuation-snapshots"),
        json={
            "component_type": component_type,
            "as_of_date": as_of_date.isoformat(),
            "value": str(value),
            "currency": "SGD",
            "source": source,
            "notes": notes,
        },
    )
    assert response.status_code == 201, (
        f"manual valuation snapshot create failed for {component_type}: {response.status_code} {response.text}"
    )
    return response.json()


@ac_proof(
    "personal-financial-report-package-post-merge",
    ac_ids=[
        "AC-reporting.balance-sheet.1",
        "AC-reporting.balance-sheet.4",
        "AC-reporting.income-statement.3",
        "AC-reporting.cash-flow.1",
        "AC5.8.1",
        "AC-reporting.package-notes.3",
        "AC-reporting.package-traceability.3",
        "AC-reporting.package-traceability.4",
        "AC11.8.3",
        "AC11.9.1",
        "AC11.9.2",
        "AC11.9.3",
        "AC11.11.1",
        "AC11.11.2",
        "AC-portfolio.report-schedule.1",
        "AC-portfolio.report-schedule.2",
        "AC-portfolio.fixtures.1",
        "AC-portfolio.fixtures.2",
        "AC-portfolio.fixtures.3",
        "AC-testing.product-gates.8",
        "AC-testing.product-gates.9",
        "AC-testing.product-gates.10",
        "AC-testing.product-gates.11",
        "AC-testing.product-gates.12",
    ],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=[
        "bank_statement",
        "brokerage_statement",
        "property_statement",
        "liability_statement",
        "esop_rsu_plan",
        "csv_export",
        "manual_record",
    ],
    mirror_proof_id="personal-package-source-trust-pr",
    issue="#573",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_personal_financial_report_package_post_merge_journey(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-005 EPIC-008 EPIC-011 EPIC-017 EPIC-020.

    AC-reporting.balance-sheet.1 AC-reporting.balance-sheet.4
    AC-reporting.income-statement.3 AC-reporting.cash-flow.1 AC5.8.1
    AC-reporting.package-notes.3 AC-reporting.package-traceability.3
    AC-reporting.package-traceability.4
    AC11.8.3 AC11.9.1 AC11.9.2 AC11.9.3 AC11.11.1 AC11.11.2
    AC-portfolio.report-schedule.1 AC-portfolio.report-schedule.2
    AC-portfolio.fixtures.1 AC-portfolio.fixtures.2 AC-portfolio.fixtures.3
    AC-testing.product-gates.8 AC-testing.product-gates.9 AC-testing.product-gates.10 AC-testing.product-gates.11 AC-testing.product-gates.12:
    one complete fresh-user report package with bank data, brokerage import,
    investment performance schedule, annualized income and restricted
    compensation schedule, manual valuation, restricted notes, and source
    traceability.
    """
    page = authenticated_page_unique
    expected = PACKAGE_FIXTURE.expected_outputs
    fixture_period_start = expected.period_start
    fixture_period_end = expected.period_end

    headers = await _auth_headers(page)

    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        bank_statement_id = await _upload_bank_csv(
            client, FIXTURE_PATH, institution=BANK_INSTITUTION
        )
        parsed_bank = await _wait_for_parsed_statement(
            client,
            bank_statement_id,
            gate_name="bank CSV",
        )
        assert len(parsed_bank.get("transactions") or []) == expected.transaction_count

        approve_response = await client.post(
            _api_url(f"/statements/{bank_statement_id}/review/approve"),
            json={"create_account_if_missing": True},
        )
        assert approve_response.status_code == 200, (
            f"bank stage 1 approve failed: {approve_response.status_code} {approve_response.text}"
        )
        approve_payload = approve_response.json()
        assert approve_payload["journal_entries_created"] == expected.transaction_count

        journal_response = await client.get(_api_url("/journal-entries?limit=20"))
        assert journal_response.status_code == 200, (
            f"journal entry check failed: {journal_response.status_code} {journal_response.text}"
        )
        journal_payload = journal_response.json()
        assert journal_payload["total"] == expected.transaction_count
        assert len(journal_payload["items"]) == expected.transaction_count
        _assert_traceability(parsed_bank["transactions"], journal_payload["items"])

        first_reconciliation = await client.post(
            _api_url("/reconciliation/runs"),
            json={"statement_id": bank_statement_id},
        )
        assert first_reconciliation.status_code == 200, (
            f"first reconciliation failed: {first_reconciliation.status_code} {first_reconciliation.text}"
        )
        assert first_reconciliation.json() == {
            "matches_created": expected.transaction_count,
            "auto_accepted": expected.transaction_count,
            "pending_review": 0,
            "unmatched": 0,
        }

        second_reconciliation = await client.post(
            _api_url("/reconciliation/runs"),
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
            f"stage 2 queue failed: {stage2_queue.status_code} {stage2_queue.text}"
        )
        stage2_payload = stage2_queue.json()
        assert stage2_payload["pending_matches"] == []
        assert stage2_payload["has_unresolved_checks"] is False

        model = await _default_image_model(client)
        brokerage_statement_id = await _upload_brokerage_pdf(
            client,
            source=BROKERAGE_SOURCE,
            institution=BROKERAGE_INSTITUTION,
            model=model,
        )
        parsed_brokerage = await _wait_for_parsed_statement(
            client,
            brokerage_statement_id,
            gate_name="brokerage PDF",
            require_transactions=False,
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
            (money_amount(item["market_value"]) for item in holdings), Decimal("0.00")
        )
        assert len(holdings) == expected.brokerage_position_count, (
            f"unexpected brokerage holdings: {holdings}"
        )
        assert brokerage_value == expected.brokerage_market_value, (
            f"unexpected brokerage value: {holdings}"
        )
        primary_holding = holdings[0]

        price_update_response = await client.post(
            _api_url("/portfolio/prices/update"),
            json={
                "updates": [
                    {
                        "asset_identifier": primary_holding["asset_identifier"],
                        "price": str(expected.market_price),
                        "currency": primary_holding["currency"],
                        "price_date": expected.market_price_date.isoformat(),
                    }
                ]
            },
        )
        assert price_update_response.status_code == 200, (
            f"market price update failed: {price_update_response.status_code} {price_update_response.text}"
        )
        assert price_update_response.json()["updated_count"] == 1

        dividend_response = await client.post(
            _api_url(
                f"/portfolio/{quote(primary_holding['asset_identifier'], safe='')}/dividends"
            ),
            json={
                "payment_date": fixture_period_end.isoformat(),
                "amount": str(expected.dividend_income),
                "currency": primary_holding["currency"],
            },
        )
        assert dividend_response.status_code == 201, (
            f"dividend create failed: {dividend_response.status_code} {dividend_response.text}"
        )
        assert (
            money_amount(dividend_response.json()["amount"]) == expected.dividend_income
        )

        schedule_response = await client.get(
            _api_url(
                "/portfolio/performance/report-schedule"
                f"?period_start={fixture_period_start.isoformat()}"
                f"&period_end={fixture_period_end.isoformat()}"
                f"&as_of_date={fixture_period_end.isoformat()}&currency=SGD"
            )
        )
        assert schedule_response.status_code == 200, (
            f"investment performance schedule failed: {schedule_response.status_code} {schedule_response.text}"
        )
        schedule = schedule_response.json()
        assert schedule["period_start"] == fixture_period_start.isoformat()
        assert schedule["period_end"] == fixture_period_end.isoformat()
        assert schedule["as_of_date"] == fixture_period_end.isoformat()
        assert schedule["currency"] == "SGD"
        assert schedule["holdings"], f"investment schedule has no holdings: {schedule}"
        assert money_amount(schedule["dividend_income"]) == expected.dividend_income
        assert (
            money_amount(schedule["holdings"][0]["dividend_income"])
            == expected.dividend_income
        )
        assert money_amount(schedule["unrealized_pnl"]) >= Decimal("0.00")
        assert "data_freshness" in schedule
        assert schedule["data_freshness"]["manual_override_basis"] == (
            f"{primary_holding['asset_identifier']}:{expected.market_price_date.isoformat()}"
        )
        latest_price_date = date.fromisoformat(
            schedule["data_freshness"]["latest_price_date"]
        )
        assert latest_price_date >= expected.market_price_date
        assert schedule["source_links"], (
            f"investment schedule missing source links: {schedule}"
        )
        assert _has_price_source_link(schedule["source_links"]), (
            f"investment schedule missing price source evidence: {schedule}"
        )
        assert schedule["notes"], f"investment schedule missing notes: {schedule}"

        await page.goto(_get_url("/portfolio"))
        await expect(
            page.get_by_text("Investment Performance Report Schedule")
        ).to_be_visible()
        await expect(
            page.get_by_text("investment_performance", exact=True)
        ).to_be_visible()

        property_snapshot = await _create_manual_snapshot(
            client,
            component_type="property_value",
            as_of_date=fixture_period_end,
            value=PROPERTY_VALUE,
            source=PROPERTY_SOURCE,
            notes=PROPERTY_NOTES,
        )
        mortgage_snapshot = await _create_manual_snapshot(
            client,
            component_type="mortgage_balance",
            as_of_date=fixture_period_end,
            value=MORTGAGE_BALANCE,
            source=MORTGAGE_SOURCE,
            notes=MORTGAGE_NOTES,
        )
        esop_snapshot = await _create_manual_snapshot(
            client,
            component_type="esop",
            as_of_date=fixture_period_end,
            value=ESOP_VALUE,
            source=ESOP_SOURCE,
            notes=ESOP_NOTES,
        )
        rsu_snapshot = await _create_manual_snapshot(
            client,
            component_type="rsu",
            as_of_date=fixture_period_end,
            value=RSU_VALUE,
            source=RSU_SOURCE,
            notes=RSU_NOTES,
        )
        stock_options_snapshot = await _create_manual_snapshot(
            client,
            component_type="stock_options",
            as_of_date=fixture_period_end,
            value=STOCK_OPTIONS_VALUE,
            source=STOCK_OPTIONS_SOURCE,
            notes=STOCK_OPTIONS_NOTES,
        )

        assert property_snapshot["liquidity_class"] == "illiquid"
        assert mortgage_snapshot["liquidity_class"] == "liability"
        assert esop_snapshot["liquidity_class"] == "restricted"
        assert rsu_snapshot["liquidity_class"] == "restricted"
        assert stock_options_snapshot["liquidity_class"] == "restricted"

        manual_components_response = await client.get(
            _api_url(
                f"/assets/valuation-components?as_of_date={fixture_period_end.isoformat()}&include_restricted=true"
            )
        )
        assert manual_components_response.status_code == 200, (
            f"valuation components check failed: {manual_components_response.status_code} {manual_components_response.text}"
        )
        manual_components = manual_components_response.json()

        values_by_type_source = {
            (item["component_type"], item["source"]): money_amount(item["value"])
            for item in manual_components["items"]
        }
        assert (
            values_by_type_source[("property_value", PROPERTY_SOURCE)] == PROPERTY_VALUE
        )
        assert (
            values_by_type_source[("mortgage_balance", MORTGAGE_SOURCE)]
            == MORTGAGE_BALANCE
        )
        assert values_by_type_source[("esop", ESOP_SOURCE)] == ESOP_VALUE
        assert values_by_type_source[("rsu", RSU_SOURCE)] == RSU_VALUE
        assert (
            values_by_type_source[("stock_options", STOCK_OPTIONS_SOURCE)]
            == STOCK_OPTIONS_VALUE
        )

        snapshots_response = await client.get(
            _api_url(
                f"/assets/valuation-snapshots?as_of_date={fixture_period_end.isoformat()}"
            )
        )
        assert snapshots_response.status_code == 200, (
            f"valuation snapshot list failed: {snapshots_response.status_code} {snapshots_response.text}"
        )
        snapshots = snapshots_response.json()["items"]
        notes_by_source = {
            snapshot["source"]: snapshot["notes"] for snapshot in snapshots
        }
        assert notes_by_source[ESOP_SOURCE] == ESOP_NOTES
        assert notes_by_source[RSU_SOURCE] == RSU_NOTES
        assert notes_by_source[STOCK_OPTIONS_SOURCE] == STOCK_OPTIONS_NOTES

        restricted_response = await client.get(
            _api_url(f"/assets/restricted?as_of_date={fixture_period_end.isoformat()}")
        )
        assert restricted_response.status_code == 200, (
            f"restricted holdings check failed: {restricted_response.status_code} {restricted_response.text}"
        )
        restricted_holdings = restricted_response.json()
        assert {item["ticker"] for item in restricted_holdings} == {
            ESOP_SOURCE,
            RSU_SOURCE,
            STOCK_OPTIONS_SOURCE,
        }
        schedules_by_ticker = {
            item["ticker"]: item["vesting_schedule"] for item in restricted_holdings
        }
        assert schedules_by_ticker[ESOP_SOURCE] == ESOP_NOTES
        assert schedules_by_ticker[RSU_SOURCE] == RSU_NOTES
        assert schedules_by_ticker[STOCK_OPTIONS_SOURCE] == STOCK_OPTIONS_NOTES

        annualized_response = await client.get(
            _api_url(
                f"/reports/package/annualized-income-schedule?as_of_date={fixture_period_end.isoformat()}"
            )
        )
        assert annualized_response.status_code == 200, (
            f"annualized income schedule failed: {annualized_response.status_code} {annualized_response.text}"
        )
        annualized = annualized_response.json()
        assert annualized["section_id"] == "annualized_income_long_term"
        assert annualized["as_of_date"] == fixture_period_end.isoformat()
        assert annualized["trailing_period_days"] == 365
        assert money_amount(annualized["income"]["annualized_total"]) == money_amount(
            expected.income
        )
        assert annualized["income"]["currency"] == "SGD"
        assert annualized["income"]["calculation_basis"] == (
            "posted_or_reconciled_income_journal_lines_trailing_12_months"
        )
        assert money_amount(annualized["restricted_fair_value_total"]) == (
            ESOP_VALUE + RSU_VALUE + STOCK_OPTIONS_VALUE
        )
        assert annualized["net_worth_treatment"]["liquid_net_worth_default"] == (
            "exclude_restricted_holdings"
        )
        annualized_holdings = {
            holding["ticker"]: holding for holding in annualized["restricted_holdings"]
        }
        assert annualized_holdings[ESOP_SOURCE]["vesting_schedule"] == ESOP_NOTES
        assert annualized_holdings[RSU_SOURCE]["vesting_schedule"] == RSU_NOTES
        assert (
            annualized_holdings[STOCK_OPTIONS_SOURCE]["vesting_schedule"]
            == STOCK_OPTIONS_NOTES
        )
        assert {
            holding["compensation_type"] for holding in annualized_holdings.values()
        } == {
            "esop",
            "rsu",
            "stock_options",
        }

        notes_response = await client.get(_api_url("/reports/package/notes"))
        assert notes_response.status_code == 200, (
            f"package notes failed: {notes_response.status_code} {notes_response.text}"
        )
        package_notes = notes_response.json()
        assert package_notes["section_id"] == "notes"
        package_note_ids = {note["note_id"] for note in package_notes["notes"]}
        assert PACKAGE_FIXTURE.required_note_ids <= package_note_ids
        assert "not a regulated filing" in package_notes["non_compliance_statement"]
        assert "not legal advice" in package_notes["non_compliance_statement"]
        assert "not tax advice" in package_notes["non_compliance_statement"]
        assert "US GAAP compliant" not in package_notes["non_compliance_statement"]
        assert "HKEX filing" not in package_notes["non_compliance_statement"]

        traceability_response = await client.get(
            _api_url(
                "/reports/package/traceability"
                f"?start_date={fixture_period_start.isoformat()}"
                f"&end_date={fixture_period_end.isoformat()}"
                f"&as_of_date={fixture_period_end.isoformat()}"
            )
        )
        assert traceability_response.status_code == 200, (
            f"package traceability failed: {traceability_response.status_code} {traceability_response.text}"
        )
        traceability = traceability_response.json()
        assert traceability["section_id"] == "traceability_appendix"
        assert traceability["status"] == "ready"
        assert _has_dynamic_traceability_identifiers(traceability)
        traceability_lines = {line["line_id"]: line for line in traceability["lines"]}
        trusted_total_line_ids = PACKAGE_FIXTURE.required_traceability_line_ids
        assert trusted_total_line_ids <= set(traceability_lines)
        for line_id in trusted_total_line_ids:
            line = traceability_lines[line_id]
            assert line["source_anchor"]["state"] == "available"
            assert line["ledger_anchor"]["state"] == "available"
            assert line["ledger_anchor"]["entry_statuses"] == ["posted", "reconciled"]
            assert line["confidence_tier"] == "TRUSTED"
        assert (
            traceability_lines[
                "annualized_income_long_term.restricted_fair_value_total"
            ]["ledger_anchor"]["state"]
            == "not_applicable"
        )
        warning_codes = {
            warning["code"] for warning in traceability["completeness_warnings"]
        }
        assert {
            "missing_source_anchor",
            "manual_only_source",
            "stale_market_data",
        } <= warning_codes

        manual_components_exclusive = await client.get(
            _api_url(
                f"/assets/valuation-components?as_of_date={fixture_period_end.isoformat()}&include_restricted=false"
            )
        )
        assert manual_components_exclusive.status_code == 200, (
            f"valuation components exclusive check failed: {manual_components_exclusive.status_code} {manual_components_exclusive.text}"
        )
        manual_components_exclusive_payload = manual_components_exclusive.json()
        sources_exclusive = {
            (item["component_type"], item["source"])
            for item in manual_components_exclusive_payload["items"]
        }
        assert ("esop", ESOP_SOURCE) not in sources_exclusive
        assert ("rsu", RSU_SOURCE) not in sources_exclusive
        assert ("stock_options", STOCK_OPTIONS_SOURCE) not in sources_exclusive

        expected_bank_cash = expected.bank_cash
        expected_manual_assets = expected.manual_asset_total
        expected_assets = expected.total_assets(brokerage_value)
        expected_liabilities = expected.manual_liability_total
        expected_net_worth_adjustment = expected.net_worth_adjustment_gain_loss

        assert money_amount(manual_components["total_assets"]) == expected_manual_assets
        assert (
            money_amount(manual_components["total_liabilities"]) == expected_liabilities
        )
        assert (
            money_amount(manual_components["net_worth_delta"])
            == expected_manual_assets - expected_liabilities
        )

        balance_payload = await client.get(
            _api_url(
                f"/reports/balance-sheet?as_of_date={fixture_period_end.isoformat()}&currency=SGD&include_restricted=true"
            )
        )
        assert balance_payload.status_code == 200, (
            f"balance sheet failed: {balance_payload.status_code} {balance_payload.text}"
        )
        balance = balance_payload.json()
        assert money_amount(balance["total_assets"]) == expected_assets
        assert money_amount(balance["total_liabilities"]) == expected_liabilities
        assert (
            money_amount(balance["total_equity"])
            == expected_assets - expected_liabilities
        )
        assert (
            money_amount(balance["net_worth_adjustment_gain_loss"])
            == expected_net_worth_adjustment
        )
        assert money_amount(balance["equation_delta"]) == Decimal("0.00")
        assert balance["is_balanced"] is True
        assert _line_total(balance["assets"]) == money_amount(balance["total_assets"])
        assert _line_total(balance["liabilities"]) == money_amount(
            balance["total_liabilities"]
        )

        income_payload = await client.get(
            _api_url(
                f"/reports/income-statement?start_date={fixture_period_start.isoformat()}&end_date={fixture_period_end.isoformat()}&currency=SGD"
            )
        )
        assert income_payload.status_code == 200, (
            f"income statement failed: {income_payload.status_code} {income_payload.text}"
        )
        income = income_payload.json()
        assert money_amount(income["total_income"]) == expected.income
        assert money_amount(income["total_expenses"]) == expected.expenses
        assert money_amount(income["net_income"]) == expected.net_income

        cash_flow_payload = await client.get(
            _api_url(
                f"/reports/cash-flow?start_date={fixture_period_start.isoformat()}&end_date={fixture_period_end.isoformat()}&currency=SGD"
            )
        )
        assert cash_flow_payload.status_code == 200, (
            f"cash flow failed: {cash_flow_payload.status_code} {cash_flow_payload.text}"
        )
        cash_flow = cash_flow_payload.json()
        assert money_amount(cash_flow["summary"]["net_cash_flow"]) == money_amount(
            expected.net_income
        )
        assert money_amount(cash_flow["summary"]["beginning_cash"]) == Decimal("0.00")
        assert money_amount(cash_flow["summary"]["ending_cash"]) == money_amount(
            expected_bank_cash
        )

        bs_export = await client.get(
            _api_url("/reports/export"),
            params={
                "report_type": "balance-sheet",
                "format": "csv",
                "as_of_date": fixture_period_end.isoformat(),
                "currency": "SGD",
            },
        )
        assert bs_export.status_code == 200, (
            f"balance-sheet export failed: {bs_export.status_code} {bs_export.text}"
        )
        assert "text/csv" in bs_export.headers["content-type"]
        _assert_csv_total(
            bs_export.text, "Total Assets", money_amount(balance["total_assets"])
        )
        _assert_csv_total(
            bs_export.text,
            "Total Liabilities",
            money_amount(balance["total_liabilities"]),
        )

        income_export = await client.get(
            _api_url("/reports/export"),
            params={
                "report_type": "income-statement",
                "format": "csv",
                "start_date": fixture_period_start.isoformat(),
                "end_date": fixture_period_end.isoformat(),
                "currency": "SGD",
            },
        )
        assert income_export.status_code == 200, (
            f"income export failed: {income_export.status_code} {income_export.text}"
        )
        assert "text/csv" in income_export.headers["content-type"]
        _assert_csv_total(
            income_export.text, "Total Income", money_amount(income["total_income"])
        )
        _assert_csv_total(
            income_export.text, "Total Expenses", money_amount(income["total_expenses"])
        )
        _assert_csv_total(
            income_export.text, "Net Income", money_amount(income["net_income"])
        )

    await page.goto(_get_url("/dashboard"))
    await page.wait_for_load_state("domcontentloaded")
    await expect(page.get_by_label("Upload-to-report home")).to_be_visible(
        timeout=10_000
    )
    await expect(page.get_by_text("Loading upload-to-report workflow...")).to_be_hidden(
        timeout=30_000
    )
    await expect(page.get_by_label("Dashboard analytics", exact=True)).to_be_visible(
        timeout=10_000
    )

    await page.goto(
        _get_url(
            f"/reports/balance-sheet?as_of_date={fixture_period_end.isoformat()}&currency=SGD"
        )
    )
    await page.wait_for_load_state("domcontentloaded")
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=10_000
    )

    await page.goto(
        _get_url(
            f"/reports/income-statement?start_date={fixture_period_start.isoformat()}&end_date={fixture_period_end.isoformat()}&currency=SGD"
        )
    )
    await page.wait_for_load_state("domcontentloaded")
    await expect(page.get_by_role("heading", name="Income Statement")).to_be_visible(
        timeout=10_000
    )

    await page.goto(
        _get_url(
            f"/reports/cash-flow?start_date={fixture_period_start.isoformat()}&end_date={fixture_period_end.isoformat()}&currency=SGD"
        )
    )
    await page.wait_for_load_state("domcontentloaded")
    await expect(page.get_by_role("heading", name="Cash Flow Statement")).to_be_visible(
        timeout=10_000
    )
