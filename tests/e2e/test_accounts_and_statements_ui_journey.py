from __future__ import annotations

import pytest
from playwright.async_api import Page, expect
from tests.benchmarks.statement_generators import generate_standard_operations_csv

from tests.e2e._journey_helpers import get_url, setup_runner_page


@pytest.mark.e2e
async def test_accounts_surface_and_balance_display(page: Page) -> None:
    await setup_runner_page(
        page,
        "accounts_journey",
        (
            ("Main Operating Cash", "ASSET"),
            ("Founding Equity", "EQUITY"),
            ("Software Subscription", "EXPENSE"),
        ),
    )
    await page.goto(get_url("/settings?tab=accounts"), wait_until="domcontentloaded")
    assert "/login" not in page.url
    await expect(
        page.get_by_role("heading", name="Accounts", exact=True)
    ).to_be_visible(timeout=15000)
    await expect(page.get_by_role("button", name="Add Account")).to_be_visible(
        timeout=10000
    )
    for text in ("Main Operating Cash", "Founding Equity", "Software Subscription"):
        await expect(page.get_by_text(text)).to_be_visible(timeout=10000)
    asset_tab = page.get_by_role("button", name="ASSET", exact=True)
    if await asset_tab.count() > 0:
        await asset_tab.click()
        await expect(page.get_by_text("Main Operating Cash")).to_be_visible()


@pytest.mark.e2e
async def test_statement_detail_and_review_surface(page: Page) -> None:
    stmt_id = await setup_runner_page(
        page,
        "statements_journey",
        (("Operating Cash", "ASSET"),),
        csv_bytes=generate_standard_operations_csv(),
    )
    await page.goto(get_url(f"/statements/{stmt_id}"), wait_until="domcontentloaded")
    assert "/login" not in page.url
    await expect(page.locator("body")).to_be_visible(timeout=15000)
    await expect(
        page.get_by_test_id("stage1-desktop-transaction-region").get_by_text(
            "CONSULTING SERVICES REVENUE"
        )
    ).to_be_visible(timeout=15000)
