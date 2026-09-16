"""Live GXS source-to-saved-report proof using the product's business UI.

Authentication setup may use the API. Account creation, PDF upload, economic
review, approval, snapshot generation, reopen and downloads use browser controls.
The committed generated fixture, never provider output, owns expected numbers.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof
from playwright.async_api import Page, expect

from pdf_fixture_paths import committed_fixture_pdf

APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
EXPECTED_PATH = (
    Path(__file__).resolve().parents[2]
    / "common/testing/fixtures/pdf/generated/gxs_statement_fixture_expected.json"
)
# These are independent fixture meanings, not classifications copied from OCR.
DISPOSITIONS = {
    "Interest Earned": ("income", "INTEREST"),
    "PayNow from ALVIN GOH": ("income", "OTHER_INCOME"),
    "Payment to GrabPay Wallet": ("expense", "TRANSPORT"),
    "PayNow to MERCHANT HAWKER": ("expense", "DINING"),
}


@ac_proof(
    "gxs-browser-saved-package",
    ac_ids=["AC-testing.package-lifecycle.3"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="extraction-corpus-journeys-pr",
    issue="#2008",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_gxs_browser_upload_to_saved_package(
    authenticated_page_unique: Page, tmp_path: Path, record_property
) -> None:
    """EPIC-003 EPIC-008: AC-testing.package-lifecycle.3, no API business seeding."""
    started = time.monotonic()
    page = authenticated_page_unique
    expected = json.loads(EXPECTED_PATH.read_text())
    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, "live browser proof requires an explicit EXPECTED_SHA"
    for path in ("/api/health", "/frontend-version.json"):
        response = await page.request.get(f"{APP_URL}{path}")
        assert response.status == 200
        version = (await response.json())["git_sha"]
        assert version == expected_version, f"{path} is not the pinned deployment"
        record_property(path, version)

    await page.goto(f"{APP_URL}/upload")
    await page.locator('[data-testid="uploader-institution-statement"]').fill(
        "GXS Generated Browser Proof"
    )
    model = page.locator('[data-testid="uploader-model-statement"]')
    await expect(model).not_to_have_value("")
    record_property("requested_ocr_model", await model.input_value())
    pdf = tmp_path / "gxs-browser-proof.pdf"
    pdf.write_bytes(
        committed_fixture_pdf("gxs_statement_fixture.pdf").read_bytes()
        + f"\n% generated browser proof {uuid.uuid4()}\n".encode()
    )
    await page.set_input_files('[data-testid="uploader-file-statement"]', str(pdf))
    async with page.expect_response(
        lambda response: "/api/statements/upload" in response.url
    ) as pending:
        await page.get_by_role("button", name="Upload & Parse Statement").click()
    uploaded = await pending.value
    assert uploaded.status in (200, 201, 202)
    statement_id = (await uploaded.json())["id"]
    record_property("source_statement_id", statement_id)
    deadline = time.monotonic() + int(os.getenv("PARSING_TIMEOUT_MS", "480000")) / 1000
    while time.monotonic() < deadline:
        response = await page.request.get(f"{APP_URL}/api/statements/{statement_id}")
        assert response.status == 200
        source = await response.json()
        if source["status"] in ("parsed", "approved", "rejected"):
            break
        await asyncio.sleep(2)
    else:
        pytest.fail("Generated GXS source did not reach a terminal parse state")
    assert source["status"] in ("parsed", "approved"), source.get("validation_error")
    actual_rows = sorted(
        (row["txn_date"], Decimal(row["amount"]), row["direction"], row["currency"])
        for row in source["transactions"]
    )
    assert actual_rows == sorted(
        (row["date"], Decimal(row["amount"]), row["direction"], row["currency"])
        for row in expected["events"]
    )

    await page.goto(f"{APP_URL}/statements/{statement_id}/review")
    await page.get_by_role("link", name="Review transaction classifications").click()
    created_account_types: set[str] = set()
    for row in expected["events"]:
        transaction = page.get_by_role(
            "button",
            name=re.compile(
                re.escape(row["description"]) + r".*" + re.escape(row["date"]), re.S
            ),
        )
        await transaction.click()
        detail = page.get_by_text("Reviewed Disposition", exact=True).locator("..")
        await expect(detail).to_contain_text(row["date"])
        intent, category = DISPOSITIONS[row["description"]]
        await page.get_by_label("Economic intent").select_option(intent)
        await page.get_by_label("Report category").fill(category)
        await page.get_by_label("Review rationale").fill(
            "The independent generated GXS fixture declares this economic meaning."
        )
        if intent not in created_account_types:
            await page.get_by_role(
                "button", name="Create counter account", exact=True
            ).click()
            account_dialog = page.get_by_role("dialog", name="New Account", exact=True)
            await expect(
                account_dialog.get_by_label("Type *", exact=True)
            ).to_have_value(intent.upper())
            await account_dialog.get_by_placeholder("e.g., Cash on Hand").fill(
                f"Generated {intent.upper()}"
            )
            async with page.expect_response(
                lambda response: "/api/accounts" in response.url
                and response.request.method == "POST"
            ) as pending:
                await account_dialog.get_by_role(
                    "button", name="Create Account", exact=True
                ).click()
            assert (await pending.value).status == 201
            await expect(account_dialog).not_to_be_visible()
            await expect(detail).to_contain_text(row["date"])
            await expect(page.get_by_label("Economic intent")).to_have_value(intent)
            await expect(page.get_by_label("Report category")).to_have_value(category)
            await expect(page.get_by_label("Review rationale")).to_have_value(
                "The independent generated GXS fixture declares this economic meaning."
            )
            await expect(page.get_by_label("Counter account")).to_have_value("")
            await expect(
                page.get_by_role("button", name="Confirm and Post", exact=True)
            ).to_be_disabled()
            created_account_types.add(intent)
        await page.get_by_label("Counter account").select_option(
            label=f"Generated {intent.upper()} · {intent.upper()}"
        )
        async with page.expect_response(
            lambda response: "/reviewed-disposition" in response.url
            and response.request.method == "POST"
        ) as pending:
            await page.get_by_role(
                "button", name="Confirm and Post", exact=True
            ).click()
        posted = await pending.value
        assert posted.status == 200, await posted.text()
        await expect(transaction).not_to_be_visible()
    record_property("browser_created_counter_accounts", len(created_account_types))
    record_property("browser_counter_account_entry", "inline classification review")
    record_property("browser_economic_review_decisions", len(expected["events"]))
    await page.get_by_role("link", name="Return to statement review").first.click()
    await page.get_by_role("button", name="Approve", exact=True).click()
    async with page.expect_response(
        lambda response: "/review/approve" in response.url
    ) as pending:
        await (
            page.get_by_role("dialog")
            .get_by_role("button", name="Approve", exact=True)
            .click()
        )
    assert (await pending.value).status == 200

    await page.goto(f"{APP_URL}/reports/package")
    statement = expected["statement"]
    await page.get_by_label("Package period start").fill(statement["period_start"])
    await page.get_by_label("Package report date").fill(statement["period_end"])
    await page.get_by_role("button", name="US-like", exact=True).click()
    async with page.expect_response(
        lambda response: "/reports/package/generate" in response.url
    ) as pending:
        await page.get_by_role("button", name="Generate Snapshot", exact=True).click()
    generated = await pending.value
    assert generated.status == 200
    snapshot = await generated.json()
    assert snapshot["status"] == "trusted"
    await page.reload()
    await page.get_by_role("button", name="US-like", exact=True).click()
    await page.get_by_role("button", name="Reopen", exact=True).click()
    await expect(
        page.get_by_text(f"Frozen snapshot {snapshot['id']}", exact=True)
    ).to_be_visible()
    for export_format in ("JSON", "CSV"):
        async with page.expect_download() as pending:
            await (
                page.locator("button")
                .filter(has_text=re.compile(f"^{export_format}$"))
                .click()
            )
        await (await pending.value).save_as(
            str(tmp_path / f"package.{export_format.lower()}")
        )
    artifact = json.loads((tmp_path / "package.json").read_text())
    assert artifact["document"] == snapshot["document"]
    assert artifact["start_date"] == statement["period_start"]
    assert artifact["end_date"] == statement["period_end"]
    sections = artifact["document"]["sections"]
    income = sum(
        (
            Decimal(row["amount"])
            for row in expected["events"]
            if row["direction"] == "IN"
        ),
        Decimal("0"),
    )
    expense = sum(
        (
            Decimal(row["amount"])
            for row in expected["events"]
            if row["direction"] == "OUT"
        ),
        Decimal("0"),
    )
    assert Decimal(sections["balance_sheet"]["total_assets"]) == Decimal(
        statement["closing_balance"]
    )
    summary = sections["cash_flow"]["summary"]
    assert Decimal(summary["beginning_cash"]) == Decimal(statement["opening_balance"])
    assert Decimal(summary["ending_cash"]) == Decimal(statement["closing_balance"])
    assert Decimal(sections["income_statement"]["total_income"]) == income
    assert Decimal(sections["income_statement"]["total_expenses"]) == expense
    assert Decimal(sections["income_statement"]["net_income"]) == income - expense
    assert sections["cash_flow"]["proof_state"] == "proven"
    with (tmp_path / "package.csv").open() as exported:
        rows = list(csv.DictReader(exported))
    assert {row["line_id"] for row in rows} == {
        line["line_id"] for line in sections["traceability_appendix"]["lines"]
    }
    csv_amounts = {
        row["line_id"]: Decimal(row["amount"]) for row in rows if row["amount"]
    }
    assert csv_amounts["balance_sheet.total_assets"] == Decimal(
        statement["closing_balance"]
    )
    assert csv_amounts["income_statement.total_income"] == income
    assert csv_amounts["income_statement.total_expenses"] == expense
    # AC-reporting.report-integrity.8: a later-closing source still proves
    # included movements, but its future closing balance cannot become stock.
    cutoff = (
        date.fromisoformat(statement["period_start"]) + timedelta(days=14)
    ).isoformat()
    midperiod_response = await page.request.get(
        f"{APP_URL}/api/reports/package",
        params={
            "start_date": statement["period_start"],
            "end_date": cutoff,
            "as_of_date": cutoff,
            "currency": statement["currency"],
        },
    )
    assert midperiod_response.status == 200
    midperiod = await midperiod_response.json()
    mid_sections = midperiod["sections"]
    included = [row for row in expected["events"] if row["date"] <= cutoff]
    mid_income = sum(
        (Decimal(row["amount"]) for row in included if row["direction"] == "IN"),
        Decimal("0"),
    )
    mid_expense = sum(
        (Decimal(row["amount"]) for row in included if row["direction"] == "OUT"),
        Decimal("0"),
    )
    assert Decimal(mid_sections["income_statement"]["total_income"]) == mid_income
    assert Decimal(mid_sections["income_statement"]["total_expenses"]) == mid_expense
    assert (
        Decimal(mid_sections["balance_sheet"]["total_assets"])
        == Decimal(statement["opening_balance"]) + mid_income - mid_expense
    )
    income_line = next(
        line
        for line in mid_sections["traceability_appendix"]["lines"]
        if line["line_id"] == "income_statement.total_income"
    )
    assert income_line["source_anchor"]["details"]
    assert any(
        detail["decision_id"] for detail in income_line["source_anchor"]["details"]
    )
    (tmp_path / "midperiod-package.json").write_text(json.dumps(midperiod, indent=2))
    record_property("midperiod_source_and_amount_oracle", "passed")
    record_property("browser_saved_package_oracle", "passed")
    record_property("browser_journey_seconds", round(time.monotonic() - started, 2))
    await page.screenshot(path=str(tmp_path / "saved-package.png"), full_page=True)
