from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from common.testing import money_amount
from playwright.async_api import Page, expect
from tests.fixtures.provider_review import (
    FixtureDisposition,
    approve_statement_with_fixture_review,
)

from tests.e2e._journey_helpers import (
    api_url,
    auth_headers,
    create_opening_balances,
    get_url,
    poll_statement_via_page,
    unique_pdf_copy,
    upload_statement_via_ui,
)
from tests.e2e.conftest import fail_or_skip_ai_ocr_gate
from tests.e2e.pdf_fixture_paths import committed_fixture_pdf

INSTITUTION_LABEL = "DBS E2E Full Journey"
PARSED_STATUS_BADGE_RE = re.compile("^(Parsed|Ready to review)$", re.I)
DBS_EXPECTED_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "pdf"
    / "generated"
    / "dbs_statement_fixture_expected.json"
)
DBS_EXPECTED_OPENING_BALANCE, DBS_EXPECTED_CLOSING_BALANCE, DBS_EXPECTED_CURRENCY = (
    Decimal("12000.00"),
    Decimal("15242.05"),
    "SGD",
)
DBS_DISPOSITIONS = {
    "FAST CREDIT PAYROLL ACME PTE LTD": FixtureDisposition(
        "income", "INCOME", "The DBS fixture declares salary income.", "SALARY"
    ),
    "PAYNOW TO UEN 201912345A RENT JAN": FixtureDisposition(
        "expense", "EXPENSE", "The DBS fixture declares rent expense.", "RENT"
    ),
    "GIRO SINGTEL MOBILE BILL": FixtureDisposition(
        "expense", "EXPENSE", "The DBS fixture declares utility expense.", "UTILITIES"
    ),
    "POS NTUC FAIRPRICE BEDOK": FixtureDisposition(
        "expense", "EXPENSE", "The DBS fixture declares grocery expense.", "GROCERIES"
    ),
    "FAST CREDIT FREELANCE PROJECT": FixtureDisposition(
        "income", "INCOME", "The DBS fixture declares freelance income.", "FREELANCE"
    ),
    "PAYNOW TO JOHN TAN": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The DBS fixture declares family-support expense.",
        "FAMILY_SUPPORT",
    ),
    "GIRO SP SERVICES UTILITIES": FixtureDisposition(
        "expense", "EXPENSE", "The DBS fixture declares utility expense.", "UTILITIES"
    ),
}


def test_parsed_status_badge_pattern_accepts_user_facing_ready_to_review_label() -> (
    None
):
    assert PARSED_STATUS_BADGE_RE.search("Parsed") and PARSED_STATUS_BADGE_RE.search(
        "Ready to review"
    )


def test_dbs_ground_truth_balances_stay_pinned() -> None:
    expected = json.loads(DBS_EXPECTED_PATH.read_text(encoding="utf-8"))
    stmt = expected["statement"]
    signed = sum(
        (
            Decimal(e["amount"]) if e["direction"] == "IN" else -Decimal(e["amount"])
            for e in expected["events"]
        ),
        Decimal("0.00"),
    )
    assert (
        Decimal(stmt["opening_balance"]) == DBS_EXPECTED_OPENING_BALANCE
        and Decimal(stmt["closing_balance"]) == DBS_EXPECTED_CLOSING_BALANCE
        and stmt["currency"] == DBS_EXPECTED_CURRENCY
        and stmt["balance_validated"] is True
        and DBS_EXPECTED_OPENING_BALANCE + signed == DBS_EXPECTED_CLOSING_BALANCE
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_dbs_statement_full_journey(authenticated_page_unique: Page) -> None:
    page = authenticated_page_unique
    statement_id = await upload_statement_via_ui(
        page,
        institution=INSTITUTION_LABEL,
        file_path=unique_pdf_copy(committed_fixture_pdf("dbs_statement_fixture.pdf")),
    )
    default_model = await page.locator(
        '[data-testid="uploader-model-statement"]'
    ).input_value()

    row = page.locator(".relative.block").filter(has_text=INSTITUTION_LABEL).first
    await expect(row).to_be_visible(timeout=15000)
    last_statement = await poll_statement_via_page(
        page, statement_id, timeout_ms=120000, poll_ms=3000
    )
    if (
        last_statement.get("status") == "rejected"
        or await row.locator(
            "span.badge", has_text=re.compile("^Rejected$", re.I)
        ).is_visible()
    ):
        fail_or_skip_ai_ocr_gate(
            "Statement parsing failed (status=rejected) — AI service may be unavailable or misconfigured on the test environment.",
            statement=last_statement,
            model=default_model,
        )
    await expect(
        row.locator(
            "span.badge",
            has_text=PARSED_STATUS_BADGE_RE
            if last_statement.get("status") == "parsed"
            else re.compile("^Approved$", re.I),
        )
    ).to_be_visible(timeout=15000)

    await page.goto(get_url(f"/statements/{statement_id}"))
    await expect(page).to_have_url(re.compile("/statements/[^/]+$"), timeout=15000)
    await expect(
        page.get_by_role("heading", name="Transactions", exact=True)
    ).to_be_visible(timeout=10000)
    await expect(page.locator("table tbody tr").first).to_be_visible(timeout=10000)
    if last_statement.get("status") != "approved":
        await page.get_by_role("button", name="Approve", exact=True).click()
        dialog = page.locator('[role="dialog"]')
        await expect(dialog).to_be_visible(timeout=5000)
        async with page.expect_response(
            lambda r: r.url.endswith(f"/api/statements/{statement_id}/approvals")
        ) as approval_info:
            await dialog.get_by_role("button", name="Approve", exact=True).click()
        approval_resp = await approval_info.value
        if approval_resp.status == 409:
            review_link = page.get_by_role(
                "link", name="Review transaction classifications"
            )
            await expect(review_link).to_be_visible(timeout=15000)
            await expect(review_link).to_have_attribute(
                "href",
                f"/reconciliation?tab=unmatched&statement_id={statement_id}&return_to=%2Fstatements%2F{statement_id}",
            )
            async with httpx.AsyncClient(
                headers=await auth_headers(page), verify=False, timeout=120.0
            ) as client:
                approval = await approve_statement_with_fixture_review(
                    client,
                    api_url=api_url,
                    statement_id=str(statement_id),
                    transactions=last_statement.get("transactions") or [],
                    dispositions=DBS_DISPOSITIONS,
                )
            assert approval.get("status") == "approved"
            await page.goto(get_url(f"/statements/{statement_id}"))
        else:
            assert approval_resp.status == 200, (
                f"approve failed: {approval_resp.status}"
            )
            await expect(page).to_have_url(
                re.compile("/statements/[^/?]+(?:\\?.*)?$"), timeout=15000
            )
    await expect(page.locator("span.badge", has_text="approved")).to_be_visible(
        timeout=15000
    )

    await page.goto(get_url("/upload"))
    await expect(page).to_have_url(re.compile("/upload$"), timeout=15000)
    approved_row = (
        page.locator(".relative.block").filter(has_text=INSTITUTION_LABEL).first
    )
    await expect(approved_row).to_be_visible(timeout=15000)
    await expect(
        approved_row.locator("span.badge", has_text=re.compile("^Approved$", re.I))
    ).to_be_visible(timeout=15000)

    expected = json.loads(DBS_EXPECTED_PATH.read_text(encoding="utf-8"))
    detail = await (
        await page.request.get(get_url(f"/api/statements/{statement_id}"))
    ).json()
    account_id = detail.get("account_id")
    assert (
        account_id
        and money_amount(detail["opening_balance"]) == DBS_EXPECTED_OPENING_BALANCE
        and money_amount(detail["closing_balance"]) == DBS_EXPECTED_CLOSING_BALANCE
        and (detail.get("currency") or "").upper() == DBS_EXPECTED_CURRENCY
        and len(detail.get("transactions") or []) >= len(expected["events"])
    )
    async with httpx.AsyncClient(
        headers=await auth_headers(page), verify=False, timeout=120.0
    ) as client:
        await create_opening_balances(
            client,
            entry_date=expected["statement"]["period_start"],
            balances={account_id: str(DBS_EXPECTED_OPENING_BALANCE)},
            currency=DBS_EXPECTED_CURRENCY,
            memo="DBS E2E opening balance",
        )
    report = await (
        await page.request.get(
            get_url(
                f"/api/reports/balance-sheet?as_of_date={expected['statement']['period_end']}&currency={DBS_EXPECTED_CURRENCY}"
            )
        )
    ).json()
    assert (
        money_amount(report["total_assets"]) == DBS_EXPECTED_CLOSING_BALANCE
        and report.get("opening_balance_warnings") == []
        and money_amount(report["equation_delta"]) == Decimal("0.00")
        and report["is_balanced"] is True
    )

    await page.goto(get_url("/reports?tab=balance-sheet"))
    await page.wait_for_load_state("domcontentloaded")
    closing_str = f"{int(DBS_EXPECTED_CLOSING_BALANCE):,}"
    await expect(page.get_by_text("Balance Sheet", exact=False).first).to_be_visible(
        timeout=10000
    )
    await expect(page.get_by_text("Assets", exact=False).first).to_be_visible(
        timeout=10000
    )
    await expect(page.locator("body")).to_contain_text(closing_str, timeout=10000)

    await page.goto(get_url("/dashboard"))
    await page.wait_for_load_state("domcontentloaded")
    assert "/login" not in page.url
    await expect(
        page.get_by_label("Three-statement cockpit", exact=True)
    ).to_be_visible(timeout=15000)
    balance_card = page.locator('[data-testid="cockpit-card-balance-sheet"]')
    for text in ("Total assets", closing_str, "Net worth"):
        await expect(balance_card).to_contain_text(text, timeout=15000)
    for tab, text in (
        ("income-statement", "Income Statement"),
        ("cash-flow", "Cash Flow"),
    ):
        await page.goto(get_url(f"/reports?tab={tab}"))
        await page.wait_for_load_state("domcontentloaded")
        await expect(page.get_by_text(text, exact=False).first).to_be_visible(
            timeout=10000
        )
