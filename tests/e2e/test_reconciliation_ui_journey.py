from __future__ import annotations

import pytest
from playwright.async_api import Page, expect
from tests.benchmarks.statement_generators import generate_standard_operations_csv

from tests.e2e._journey_helpers import get_url, setup_runner_page

DISPOSITION_POST_REFRESH_TIMEOUT_MS = 30000


@pytest.mark.e2e
async def test_reconciliation_workbench_surface_and_navigation(
    authenticated_page: Page,
) -> None:
    page = authenticated_page
    await page.goto(
        get_url("/reconciliation?tab=matches"), wait_until="domcontentloaded"
    )
    assert "/login" not in page.url
    await expect(
        page.get_by_role("heading", name="Reconciliation Workbench", exact=True)
    ).to_be_visible(timeout=15000)
    await expect(page.get_by_text("Match Rate")).to_be_visible(timeout=10000)
    await expect(
        page.get_by_role("heading", name="Score Distribution", exact=True)
    ).to_be_visible(timeout=10000)
    tabs = page.get_by_role("navigation", name="Reconciliation workspace views")
    for link, heading in (
        ("Unmatched", "Unmatched Transactions"),
        ("Review queue", "Review queue"),
        ("Matches", "Reconciliation Workbench"),
    ):
        await tabs.get_by_role("link", name=link).click()
        await expect(
            page.get_by_role("heading", name=heading, exact=True)
        ).to_be_visible(timeout=15000)


@pytest.mark.e2e
async def test_reconciliation_review_queue_surface(authenticated_page: Page) -> None:
    page = authenticated_page
    await page.goto(
        get_url("/reconciliation?tab=review-queue"), wait_until="domcontentloaded"
    )
    assert "/login" not in page.url
    await expect(
        page.get_by_role("heading", name="Review queue", exact=True)
    ).to_be_visible(timeout=15000)
    await expect(page.locator("body")).to_be_visible()


@pytest.mark.e2e
@pytest.mark.parse_journey
async def test_reconciliation_unmatched_interactive_disposition(page: Page) -> None:
    stmt_id = await setup_runner_page(
        page,
        "recon_disposition",
        (("Operating Cash", "ASSET"), ("Office Supplies", "EXPENSE")),
        csv_bytes=generate_standard_operations_csv(),
    )
    await page.goto(
        get_url(f"/reconciliation?tab=unmatched&statement_id={stmt_id}"),
        wait_until="domcontentloaded",
    )
    assert "/login" not in page.url
    await expect(
        page.get_by_role("heading", name="Unmatched Transactions", exact=True)
    ).to_be_visible(timeout=15000)
    txn_item = page.get_by_text("AWS CLOUD HOSTING AND SAAS")
    await expect(txn_item).to_be_visible(timeout=10000)
    await txn_item.click()
    await expect(
        page.get_by_role("heading", name="Transaction Review", exact=True)
    ).to_be_visible()
    await page.get_by_label("Transaction type").select_option(value="expense")
    counter_select = page.locator("#counter-account-select")
    await expect(counter_select).to_be_visible()
    await counter_select.select_option(label="Office Supplies · EXPENSE")
    await page.locator('input[placeholder="For example, DINING or SALARY"]').fill(
        "OFFICE_EXPENSE"
    )
    await page.locator(
        'textarea[placeholder="What source evidence supports this decision?"]'
    ).fill("Approved IT cloud infrastructure expense")
    confirm_btn = page.get_by_role("button", name="Confirm and Post")
    await expect(confirm_btn).to_be_enabled()
    await confirm_btn.click()
    await expect(page.get_by_text("3 records")).to_be_visible(
        timeout=DISPOSITION_POST_REFRESH_TIMEOUT_MS
    )
    await expect(txn_item).to_have_count(0)
