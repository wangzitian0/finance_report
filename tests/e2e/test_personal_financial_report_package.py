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
from uuid import uuid4

import httpx
import pytest
from conftest import fail_or_skip_ai_ocr_gate
from personal_report_package_fixture import PERSONAL_REPORT_PACKAGE_FIXTURE
from playwright.async_api import Page, expect

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))

def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def _auth_headers(page: Page) -> dict[str, str]:
    token = await page.evaluate("() => window.localStorage.getItem('finance_access_token')")
    assert token, "Missing finance_access_token in localStorage"
    return {"Authorization": f"Bearer {token}"}


def _statement_timeout_message(statement_id: str, last_payload: dict | None) -> str:
    if not last_payload:
        return (
            f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms; "
            "no poll payload was returned"
        )

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
    response = await client.get(_api_url("/ai/models?modality=image"))
    assert response.status_code == 200, f"model catalog request failed: {response.status_code} {response.text}"
    payload = response.json()
    return payload.get("default_model") or payload["models"][0]["id"]


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
            f"PDF fixture generation failed for {source}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    pdfs = sorted(source_dir.glob(f"test_{source}_*.pdf")) if source_dir.exists() else []
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
            assert _money(row["amount"]) == expected, (
                f"CSV section {section} mismatch: expected {expected}, got {row['amount']}"
            )
            return
    pytest.fail(
        f"CSV export missing section {section}: sections={ [row.get('section') for row in rows] }"
    )


def _assert_traceability(statement_rows: list[dict], journal_rows: list[dict]) -> None:
    txn_ids = {str(txn["id"]) for txn in statement_rows}
    matched = []
    for txn_id in txn_ids:
        related = [entry for entry in journal_rows if str(entry.get("source_id")) == txn_id]
        assert related, f"no journal entry linked to statement transaction {txn_id}"
        assert {entry.get("status") for entry in related} <= {"posted", "reconciled"}, (
            f"statement-linked entries for transaction {txn_id} must be posted/reconciled: {related}"
        )
        statement_types = {str(entry.get("source_type")) for entry in related}
        assert statement_types.issubset({"manual", "user_confirmed", "auto_matched", "auto_parsed", "bank_statement"}), (
            f"statement-linked entries for {txn_id} have unexpected source_type: {statement_types}"
        )
        matched.extend(related)

    assert matched, "expected at least one statement-linked journal entry"


def _line_total(lines: list[dict], token: str | None = None) -> Decimal:
    filtered = lines if token is None else [line for line in lines if token.lower() in str(line.get("name", "")).lower()]
    return sum((_money(line["amount"]) for line in filtered), Decimal("0.00"))


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


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_personal_financial_report_package_post_merge_journey(
    authenticated_page_unique: Page,
    tmp_path: Path,
) -> None:
    """EPIC-005 EPIC-008 EPIC-011 EPIC-017.

    AC5.1.1 AC5.1.4 AC5.2.3 AC5.3.1 AC5.8.1 AC5.12.4 AC5.13.4
    AC8.13.83 AC8.13.84 AC8.13.85 AC8.13.86
    AC11.8.3 AC11.9.1 AC11.9.2 AC11.9.3 AC11.11.1 AC11.11.2 AC17.10.1 AC17.10.2:
    one complete fresh-user report package with bank data, brokerage import,
    investment performance schedule, annualized income and restricted
    compensation schedule, manual valuation, restricted notes, and source
    traceability.
    """
    page = authenticated_page_unique
    fixture = PERSONAL_REPORT_PACKAGE_FIXTURE
    bank_fixture_path = fixture.write_bank_csv(tmp_path)
    fixture_period_start = fixture.period_start
    fixture_period_end = fixture.period_end

    headers = await _auth_headers(page)

    async with httpx.AsyncClient(headers=headers, verify=False, timeout=120.0) as client:
        contract_response = await client.get(_api_url("/reports/package/contract"))
        assert contract_response.status_code == 200, (
            f"package contract failed: {contract_response.status_code} {contract_response.text}"
        )
        contract_sections = {section["section_id"] for section in contract_response.json()["sections"]}
        assert fixture.required_sections <= contract_sections

        bank_statement_id = await _upload_bank_csv(client, bank_fixture_path, institution=fixture.institution)
        parsed_bank = await _wait_for_parsed_statement(
            client,
            bank_statement_id,
            gate_name="bank CSV",
        )
        assert len(parsed_bank.get("transactions") or []) == fixture.transaction_count

        approve_response = await client.post(
            _api_url(f"/statements/{bank_statement_id}/review/approve"),
            json={"create_account_if_missing": True},
        )
        assert approve_response.status_code == 200, (
            f"bank stage 1 approve failed: {approve_response.status_code} {approve_response.text}"
        )
        approve_payload = approve_response.json()
        assert approve_payload["journal_entries_created"] == fixture.transaction_count

        journal_response = await client.get(_api_url("/journal-entries?limit=20"))
        assert journal_response.status_code == 200, (
            f"journal entry check failed: {journal_response.status_code} {journal_response.text}"
        )
        journal_payload = journal_response.json()
        assert journal_payload["total"] == fixture.transaction_count
        assert len(journal_payload["items"]) == fixture.transaction_count
        _assert_traceability(parsed_bank["transactions"], journal_payload["items"])

        first_reconciliation = await client.post(
            _api_url("/reconciliation/run"),
            json={"statement_id": bank_statement_id},
        )
        assert first_reconciliation.status_code == 200, (
            f"first reconciliation failed: {first_reconciliation.status_code} {first_reconciliation.text}"
        )
        assert first_reconciliation.json() == {
            "matches_created": fixture.transaction_count,
            "auto_accepted": fixture.transaction_count,
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
            f"stage 2 queue failed: {stage2_queue.status_code} {stage2_queue.text}"
        )
        stage2_payload = stage2_queue.json()
        assert stage2_payload["pending_matches"] == []
        assert stage2_payload["has_unresolved_checks"] is False

        model = await _default_image_model(client)
        brokerage_statement_id = await _upload_brokerage_pdf(
            client,
            source=fixture.brokerage_source,
            institution=fixture.brokerage_institution,
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
        brokerage_value = sum((_money(item["market_value"]) for item in holdings), Decimal("0.00"))
        assert brokerage_value > Decimal("0.00"), f"brokerage holdings have no value: {holdings}"

        schedule_response = await client.get(
            _api_url(
                "/portfolio/performance/report-schedule"
                f"?period_start={fixture_period_start.isoformat()}"
                f"&period_end={fixture_period_end.isoformat()}"
                f"&as_of_date={fixture_period_end.isoformat()}&currency={fixture.currency}"
            )
        )
        assert schedule_response.status_code == 200, (
            f"investment performance schedule failed: {schedule_response.status_code} {schedule_response.text}"
        )
        schedule = schedule_response.json()
        assert schedule["period_start"] == fixture_period_start.isoformat()
        assert schedule["period_end"] == fixture_period_end.isoformat()
        assert schedule["as_of_date"] == fixture_period_end.isoformat()
        assert schedule["currency"] == fixture.currency
        assert schedule["holdings"], f"investment schedule has no holdings: {schedule}"
        assert _money(schedule["unrealized_pnl"]) >= Decimal("0.00")
        assert "data_freshness" in schedule
        assert schedule["source_links"], f"investment schedule missing source links: {schedule}"
        assert schedule["notes"], f"investment schedule missing notes: {schedule}"

        await page.goto(_get_url("/portfolio"))
        await expect(page.get_by_text("Investment Performance Report Schedule")).to_be_visible()
        await expect(page.get_by_text("investment_performance")).to_be_visible()

        property_snapshot = await _create_manual_snapshot(
            client,
            component_type=fixture.property_value.component_type,
            as_of_date=fixture_period_end,
            value=fixture.property_value.value,
            source=fixture.property_value.source,
            notes=fixture.property_value.notes,
        )
        mortgage_snapshot = await _create_manual_snapshot(
            client,
            component_type=fixture.mortgage_balance.component_type,
            as_of_date=fixture_period_end,
            value=fixture.mortgage_balance.value,
            source=fixture.mortgage_balance.source,
            notes=fixture.mortgage_balance.notes,
        )
        esop_snapshot = await _create_manual_snapshot(
            client,
            component_type=fixture.esop.component_type,
            as_of_date=fixture_period_end,
            value=fixture.esop.value,
            source=fixture.esop.source,
            notes=fixture.esop.notes,
        )
        rsu_snapshot = await _create_manual_snapshot(
            client,
            component_type=fixture.rsu.component_type,
            as_of_date=fixture_period_end,
            value=fixture.rsu.value,
            source=fixture.rsu.source,
            notes=fixture.rsu.notes,
        )
        stock_options_snapshot = await _create_manual_snapshot(
            client,
            component_type=fixture.stock_options.component_type,
            as_of_date=fixture_period_end,
            value=fixture.stock_options.value,
            source=fixture.stock_options.source,
            notes=fixture.stock_options.notes,
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
            (item["component_type"], item["source"]): _money(item["value"]) for item in manual_components["items"]
        }
        assert values_by_type_source[(fixture.property_value.component_type, fixture.property_value.source)] == (
            fixture.property_value.value
        )
        assert values_by_type_source[(fixture.mortgage_balance.component_type, fixture.mortgage_balance.source)] == (
            fixture.mortgage_balance.value
        )
        assert values_by_type_source[(fixture.esop.component_type, fixture.esop.source)] == fixture.esop.value
        assert values_by_type_source[(fixture.rsu.component_type, fixture.rsu.source)] == fixture.rsu.value
        assert values_by_type_source[(fixture.stock_options.component_type, fixture.stock_options.source)] == (
            fixture.stock_options.value
        )

        snapshots_response = await client.get(
            f"/assets/valuation-snapshots?as_of_date={fixture_period_end.isoformat()}"
        )
        assert snapshots_response.status_code == 200, (
            f"valuation snapshot list failed: {snapshots_response.status_code} {snapshots_response.text}"
        )
        snapshots = snapshots_response.json()["items"]
        notes_by_source = {snapshot["source"]: snapshot["notes"] for snapshot in snapshots}
        assert notes_by_source[fixture.esop.source] == fixture.esop.notes
        assert notes_by_source[fixture.rsu.source] == fixture.rsu.notes
        assert notes_by_source[fixture.stock_options.source] == fixture.stock_options.notes

        restricted_response = await client.get(
            f"/assets/restricted?as_of_date={fixture_period_end.isoformat()}"
        )
        assert restricted_response.status_code == 200, (
            f"restricted holdings check failed: {restricted_response.status_code} {restricted_response.text}"
        )
        restricted_holdings = restricted_response.json()
        assert {item["ticker"] for item in restricted_holdings} == {
            fixture.esop.source,
            fixture.rsu.source,
            fixture.stock_options.source,
        }
        schedules_by_ticker = {item["ticker"]: item["vesting_schedule"] for item in restricted_holdings}
        assert schedules_by_ticker[fixture.esop.source] == fixture.esop.notes
        assert schedules_by_ticker[fixture.rsu.source] == fixture.rsu.notes
        assert schedules_by_ticker[fixture.stock_options.source] == fixture.stock_options.notes

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
        assert _money(annualized["income"]["annualized_total"]) == fixture.income
        assert annualized["income"]["currency"] == fixture.currency
        assert annualized["income"]["calculation_basis"] == (
            "posted_or_reconciled_income_journal_lines_trailing_12_months"
        )
        assert _money(annualized["restricted_fair_value_total"]) == fixture.restricted_fair_value_total
        assert annualized["net_worth_treatment"]["liquid_net_worth_default"] == (
            "exclude_restricted_holdings"
        )
        annualized_holdings = {holding["ticker"]: holding for holding in annualized["restricted_holdings"]}
        assert annualized_holdings[fixture.esop.source]["vesting_schedule"] == fixture.esop.notes
        assert annualized_holdings[fixture.rsu.source]["vesting_schedule"] == fixture.rsu.notes
        assert annualized_holdings[fixture.stock_options.source]["vesting_schedule"] == fixture.stock_options.notes
        assert {holding["compensation_type"] for holding in annualized_holdings.values()} == {
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
        assert fixture.required_note_ids <= package_note_ids
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
        traceability_lines = {line["line_id"]: line for line in traceability["lines"]}
        assert fixture.required_traceability_lines <= set(traceability_lines)
        trusted_total_line_ids = {
            "balance_sheet.total_assets",
            "income_statement.total_income",
            "income_statement.total_expenses",
            "cash_flow.net_cash_flow",
            "annualized_income_long_term.annualized_total",
        }
        assert trusted_total_line_ids <= set(traceability_lines)
        for line_id in trusted_total_line_ids:
            line = traceability_lines[line_id]
            assert line["source_anchor"]["state"] == "available"
            assert line["ledger_anchor"]["state"] == "available"
            assert line["ledger_anchor"]["entry_statuses"] == ["posted", "reconciled"]
            assert line["source_anchor"]["identifiers"]
            assert line["ledger_anchor"]["identifiers"]
            assert line["confidence_tier"] == "TRUSTED"
        assert traceability_lines["annualized_income_long_term.restricted_fair_value_total"]["ledger_anchor"][
            "state"
        ] == "not_applicable"
        assert traceability_lines["annualized_income_long_term.restricted_fair_value_total"]["source_anchor"][
            "identifiers"
        ]
        warning_codes = {warning["code"] for warning in traceability["completeness_warnings"]}
        assert fixture.required_traceability_warnings <= warning_codes

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
            (item["component_type"], item["source"]) for item in manual_components_exclusive_payload["items"]
        }
        assert (fixture.esop.component_type, fixture.esop.source) not in sources_exclusive
        assert (fixture.rsu.component_type, fixture.rsu.source) not in sources_exclusive
        assert (fixture.stock_options.component_type, fixture.stock_options.source) not in sources_exclusive

        expected_bank_cash = fixture.bank_cash
        expected_assets = fixture.total_assets(brokerage_value)
        expected_liabilities = fixture.mortgage_liability
        expected_net_worth_adjustment = fixture.net_worth_adjustment_gain_loss

        assert _money(manual_components["total_assets"]) == expected_assets
        assert _money(manual_components["total_liabilities"]) == expected_liabilities
        assert _money(manual_components["net_worth_delta"]) == expected_assets - expected_liabilities

        balance_payload = await client.get(
            _api_url(
                f"/reports/balance-sheet?as_of_date={fixture_period_end.isoformat()}"
                f"&currency={fixture.currency}&include_restricted=true"
            )
        )
        assert balance_payload.status_code == 200, (
            f"balance sheet failed: {balance_payload.status_code} {balance_payload.text}"
        )
        balance = balance_payload.json()
        assert _money(balance["total_assets"]) == expected_assets
        assert _money(balance["total_liabilities"]) == expected_liabilities
        assert _money(balance["total_equity"]) == expected_assets - expected_liabilities
        assert _money(balance["net_worth_adjustment_gain_loss"]) == expected_net_worth_adjustment
        assert _money(balance["equation_delta"]) == Decimal("0.00")
        assert balance["is_balanced"] is True
        assert _line_total(balance["assets"]) == _money(balance["total_assets"])
        assert _line_total(balance["liabilities"]) == _money(balance["total_liabilities"])

        income_payload = await client.get(
            _api_url(
                f"/reports/income-statement?start_date={fixture_period_start.isoformat()}"
                f"&end_date={fixture_period_end.isoformat()}&currency={fixture.currency}"
            )
        )
        assert income_payload.status_code == 200, (
            f"income statement failed: {income_payload.status_code} {income_payload.text}"
        )
        income = income_payload.json()
        assert _money(income["total_income"]) == fixture.income
        assert _money(income["total_expenses"]) == fixture.expenses
        assert _money(income["net_income"]) == fixture.net_income

        cash_flow_payload = await client.get(
            _api_url(
                f"/reports/cash-flow?start_date={fixture_period_start.isoformat()}"
                f"&end_date={fixture_period_end.isoformat()}&currency={fixture.currency}"
            )
        )
        assert cash_flow_payload.status_code == 200, (
            f"cash flow failed: {cash_flow_payload.status_code} {cash_flow_payload.text}"
        )
        cash_flow = cash_flow_payload.json()
        assert _money(cash_flow["summary"]["net_cash_flow"]) == fixture.net_income
        assert _money(cash_flow["summary"]["beginning_cash"]) == Decimal("0.00")
        assert _money(cash_flow["summary"]["ending_cash"]) == _money(expected_bank_cash)

        bs_export = await client.get(
            "/api/reports/export",
            params={
                "report_type": "balance-sheet",
                "format": "csv",
                "as_of_date": fixture_period_end.isoformat(),
                "currency": fixture.currency,
            },
        )
        assert bs_export.status_code == 200, f"balance-sheet export failed: {bs_export.status_code} {bs_export.text}"
        assert "text/csv" in bs_export.headers["content-type"]
        _assert_csv_total(bs_export.text, "Total Assets", _money(balance["total_assets"]))
        _assert_csv_total(
            bs_export.text,
            "Total Liabilities",
            _money(balance["total_liabilities"]),
        )

        income_export = await client.get(
            "/api/reports/export",
            params={
                "report_type": "income-statement",
                "format": "csv",
                "start_date": fixture_period_start.isoformat(),
                "end_date": fixture_period_end.isoformat(),
                "currency": fixture.currency,
            },
        )
        assert income_export.status_code == 200, (
            f"income export failed: {income_export.status_code} {income_export.text}"
        )
        assert "text/csv" in income_export.headers["content-type"]
        _assert_csv_total(income_export.text, "Total Income", _money(income["total_income"]))
        _assert_csv_total(income_export.text, "Total Expenses", _money(income["total_expenses"]))
        _assert_csv_total(income_export.text, "Net Income", _money(income["net_income"]))

    await page.goto(_get_url("/dashboard"))
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Dashboard")).to_be_visible(timeout=10_000)

    await page.goto(
        _get_url(
            f"/reports/balance-sheet?as_of_date={fixture_period_end.isoformat()}&currency={fixture.currency}"
        )
    )
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(timeout=10_000)

    await page.goto(
        _get_url(
            f"/reports/income-statement?start_date={fixture_period_start.isoformat()}"
            f"&end_date={fixture_period_end.isoformat()}&currency={fixture.currency}"
        )
    )
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Income Statement")).to_be_visible(timeout=10_000)

    await page.goto(
        _get_url(
            f"/reports/cash-flow?start_date={fixture_period_start.isoformat()}"
            f"&end_date={fixture_period_end.isoformat()}&currency={fixture.currency}"
        )
    )
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Cash Flow Statement")).to_be_visible(timeout=10_000)
