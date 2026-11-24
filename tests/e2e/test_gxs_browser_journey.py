from __future__ import annotations

import csv
import json
import re
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.async_api import Page, expect

from tests.e2e._journey_helpers import (
    assert_pinned_via_page,
    assert_statement_rows_equal,
    get_url,
    poll_statement_via_page,
    upload_statement_via_ui,
)
from tests.e2e.journey_checkpoint import checkpoint
from tests.e2e.pdf_fixture_paths import committed_fixture_pdf

EXPECTED_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/pdf/generated/gxs_statement_fixture_expected.json"
)
DISPOSITIONS = {
    "Interest Earned": ("income", "INTEREST"),
    "PayNow from ALVIN GOH": ("income", "OTHER_INCOME"),
    "Payment to GrabPay Wallet": ("expense", "TRANSPORT"),
    "PayNow to MERCHANT HAWKER": ("expense", "DINING"),
}


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_gxs_browser_upload_to_saved_package(
    authenticated_page_unique: Page, tmp_path: Path, record_property
) -> None:
    started, page, expected = (
        time.monotonic(),
        authenticated_page_unique,
        json.loads(EXPECTED_PATH.read_text()),
    )
    await assert_pinned_via_page(page, record_property)

    pdf = tmp_path / "gxs-browser-proof.pdf"
    pdf.write_bytes(
        committed_fixture_pdf("gxs_statement_fixture.pdf").read_bytes()
        + f"\n% generated browser proof {uuid.uuid4()}\n".encode()
    )
    statement_id = await upload_statement_via_ui(
        page,
        institution="GXS Generated Browser Proof",
        file_path=pdf,
    )
    record_property("source_statement_id", statement_id)
    checkpoint(record_property, "U1")

    source = await poll_statement_via_page(page, statement_id)
    assert source["status"] in ("parsed", "approved"), source.get("validation_error")
    assert_statement_rows_equal(source["transactions"], expected["events"])
    checkpoint(record_property, "U2")

    await page.goto(get_url(f"/statements/{statement_id}"))
    await page.get_by_role("link", name="Review transaction classifications").click()
    created_types: set[str] = set()
    for row in expected["events"]:
        transaction = page.get_by_role(
            "button",
            name=re.compile(
                re.escape(row["description"]) + ".*" + re.escape(row["date"]), re.S
            ),
        )
        await transaction.click()
        detail = page.get_by_text("Transaction Review", exact=True).locator("..")
        await expect(detail).to_contain_text(row["date"])
        intent, category = DISPOSITIONS[row["description"]]
        await page.get_by_label("Transaction type").select_option(intent)
        await page.get_by_label("Report category").fill(category)
        await page.get_by_label("Review rationale").fill(
            "The independent generated GXS fixture declares this economic meaning."
        )
        if intent not in created_types:
            await page.get_by_role(
                "button", name="+ Create counter account", exact=True
            ).click()
            dialog = page.get_by_role("dialog", name="New Account", exact=True)
            await expect(dialog.get_by_label("Type *", exact=True)).to_have_value(
                intent.upper()
            )
            await dialog.get_by_placeholder("e.g., Cash on Hand").fill(
                f"Generated {intent.upper()}"
            )
            async with page.expect_response(
                lambda r: "/api/accounts" in r.url and r.request.method == "POST"
            ) as pending:
                await dialog.get_by_role(
                    "button", name="Create Account", exact=True
                ).click()
            assert (await pending.value).status == 201
            await expect(dialog).not_to_be_visible()
            await expect(detail).to_contain_text(row["date"])
            for label, val in (
                ("Transaction type", intent),
                ("Report category", category),
                ("Counter account", ""),
            ):
                await expect(page.get_by_label(label)).to_have_value(val)
            await expect(
                page.get_by_role("button", name="Confirm and Post", exact=True)
            ).to_be_disabled()
            created_types.add(intent)
        await page.get_by_label("Counter account").select_option(
            label=f"Generated {intent.upper()} · {intent.upper()}"
        )
        async with page.expect_response(
            lambda r: "/reviewed-dispositions" in r.url and r.request.method == "POST"
        ) as pending:
            await page.get_by_role(
                "button", name="Confirm and Post", exact=True
            ).click()
        assert (await pending.value).status == 200
        await expect(transaction).not_to_be_visible()

    for k, v in {
        "browser_created_counter_accounts": len(created_types),
        "browser_counter_account_entry": "inline classification review",
        "browser_economic_review_decisions": len(expected["events"]),
    }.items():
        record_property(k, v)
    await page.get_by_role("link", name="Return to statement review").first.click()
    await page.get_by_role("button", name="Approve", exact=True).click()
    async with page.expect_response(lambda r: "/approvals" in r.url) as pending:
        await (
            page.get_by_role("dialog")
            .get_by_role("button", name="Approve", exact=True)
            .click()
        )
    assert (await pending.value).status == 200
    checkpoint(record_property, "U4")

    statement = expected["statement"]
    await page.goto(
        get_url(
            f"/reports?tab=package&start={statement['period_start']}&end={statement['period_end']}"
        )
    )
    await page.get_by_role("button", name="US-like", exact=True).click()
    async with page.expect_response(
        lambda r: "/reports/package/snapshots" in r.url
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
    for fmt in ("JSON", "CSV"):
        async with page.expect_download() as pending:
            await page.locator("button").filter(has_text=re.compile(f"^{fmt}$")).click()
        await (await pending.value).save_as(str(tmp_path / f"package.{fmt.lower()}"))

    artifact = json.loads((tmp_path / "package.json").read_text())
    sections = artifact["document"]["sections"]
    income = sum(
        (Decimal(r["amount"]) for r in expected["events"] if r["direction"] == "IN"),
        Decimal("0"),
    )
    expense = sum(
        (Decimal(r["amount"]) for r in expected["events"] if r["direction"] == "OUT"),
        Decimal("0"),
    )
    cf_summary = sections["cash_flow"]["summary"]
    assert (
        artifact["document"] == snapshot["document"]
        and (artifact["start_date"], artifact["end_date"])
        == (statement["period_start"], statement["period_end"])
        and Decimal(sections["balance_sheet"]["total_assets"])
        == Decimal(statement["closing_balance"])
        and Decimal(cf_summary["beginning_cash"])
        == Decimal(statement["opening_balance"])
        and Decimal(cf_summary["ending_cash"]) == Decimal(statement["closing_balance"])
        and Decimal(sections["income_statement"]["total_income"]) == income
        and Decimal(sections["income_statement"]["total_expenses"]) == expense
        and Decimal(sections["income_statement"]["net_income"]) == income - expense
        and sections["cash_flow"]["proof_state"] == "proven"
    )
    with (tmp_path / "package.csv").open() as exported:
        rows = list(csv.DictReader(exported))
    csv_amounts = {r["line_id"]: Decimal(r["amount"]) for r in rows if r["amount"]}
    assert (
        {r["line_id"] for r in rows}
        == {ln["line_id"] for ln in sections["traceability_appendix"]["lines"]}
        and csv_amounts["balance_sheet.total_assets"]
        == Decimal(statement["closing_balance"])
        and csv_amounts["income_statement.total_income"] == income
        and csv_amounts["income_statement.total_expenses"] == expense
    )

    cutoff = (
        date.fromisoformat(statement["period_start"]) + timedelta(days=14)
    ).isoformat()
    mid_resp = await page.request.get(
        get_url("/api/reports/package"),
        params={
            "start_date": statement["period_start"],
            "end_date": cutoff,
            "as_of_date": cutoff,
            "currency": statement["currency"],
        },
    )
    assert mid_resp.status == 200
    midperiod = await mid_resp.json()
    mid_sections, included = (
        midperiod["sections"],
        [r for r in expected["events"] if r["date"] <= cutoff],
    )
    mid_income = sum(
        (Decimal(r["amount"]) for r in included if r["direction"] == "IN"), Decimal("0")
    )
    mid_expense = sum(
        (Decimal(r["amount"]) for r in included if r["direction"] == "OUT"),
        Decimal("0"),
    )
    assert (
        Decimal(mid_sections["income_statement"]["total_income"]) == mid_income
        and Decimal(mid_sections["income_statement"]["total_expenses"]) == mid_expense
        and Decimal(mid_sections["balance_sheet"]["total_assets"])
        == Decimal(statement["opening_balance"]) + mid_income - mid_expense
    )
    checkpoint(record_property, "U8")

    income_line = next(
        ln
        for ln in mid_sections["traceability_appendix"]["lines"]
        if ln["line_id"] == "income_statement.total_income"
    )
    details_resp = await page.request.get(
        get_url("/api/reports/package/line-details"),
        params={
            "start_date": statement["period_start"],
            "end_date": cutoff,
            "as_of_date": cutoff,
            "currency": statement["currency"],
            "line_id": "income_statement.total_income",
            "anchor": "source_anchor",
            "limit": 500,
        },
    )
    assert details_resp.status == 200
    income_details = (await details_resp.json())["details"]
    assert (
        income_line["source_anchor"]["detail_count"] > 0
        and len(income_details) == income_line["source_anchor"]["detail_count"]
        and any(d["decision_id"] for d in income_details)
    )
    checkpoint(record_property, "U11")
    (tmp_path / "midperiod-package.json").write_text(json.dumps(midperiod, indent=2))
    for k, v in {
        "midperiod_source_and_amount_oracle": "passed",
        "browser_saved_package_oracle": "passed",
        "browser_journey_seconds": round(time.monotonic() - started, 2),
    }.items():
        record_property(k, v)
    await page.screenshot(path=str(tmp_path / "saved-package.png"), full_page=True)
