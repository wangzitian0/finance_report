"""Live opening-balance proof through the product's browser UI (#2383).

Journey checkpoint U5: the user records the opening balance through the browser.

An isolated user creates an SGD asset account in the browser. The user opens the
opening-balance dialog and records one balance on a fixed date. The balance sheet
then shows the account line and the Opening Balance Equity offset.

Authentication setup uses the API. Account creation and the balance entry use
browser controls only. The constants in this file own every expected number. The
test never reads an expected number from the app.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from common.testing.ac_proof import ac_proof
from playwright.async_api import Page, expect

from deployment_pin import assert_pinned_deployment, resolve_expected_commit
from journey_checkpoint import checkpoint

APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")

# Fixture constants. The user types OPENING_INPUT in the dialog. EXPECTED_OPENING
# is the independent oracle that the balance sheet must equal.
ACCOUNT_NAME = "U5 Opening Proof Savings"
OFFSET_ACCOUNT_NAME = "Opening Balance Equity"
CURRENCY = "SGD"
OPENING_DATE = "2025-12-31"
OPENING_INPUT = "1234.56"
EXPECTED_OPENING = Decimal("1234.56")
ZERO = Decimal("0")


def _lines_named(lines: list[dict], name: str) -> list[dict]:
    return [line for line in lines if line["name"] == name]


async def _balance_sheet(page: Page, as_of_date: str) -> dict:
    response = await page.request.get(
        f"{APP_URL}/api/reports/balance-sheet",
        params={"as_of_date": as_of_date, "currency": CURRENCY},
    )
    assert response.status == 200, await response.text()
    return await response.json()


@ac_proof(
    "opening-balance-browser-ui",
    ac_ids=["AC-ledger.first-use.2"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    issue="#2383",
    required_markers=["e2e", "journey"],
)
@pytest.mark.e2e
@pytest.mark.journey
async def test_opening_balance_recorded_through_browser(
    authenticated_page_unique: Page, record_property
) -> None:
    """EPIC-002 EPIC-008: AC-ledger.first-use.2: the browser records an opening balance (checkpoint U5)."""
    page = authenticated_page_unique
    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, "live browser proof requires an explicit EXPECTED_SHA"
    expected_commit = resolve_expected_commit(expected_version)
    for path in ("/api/health", "/frontend-version.json"):
        response = await page.request.get(f"{APP_URL}{path}")
        assert response.status == 200
        payload = await response.json()
        assert_pinned_deployment(payload, expected_version, expected_commit)
        record_property(path, payload["git_sha"])
    checkpoint(record_property, "U12")

    # Create the SGD asset account through the browser.
    await page.goto(f"{APP_URL}/accounts")
    await page.get_by_role("button", name="Add Account", exact=True).click()
    account_dialog = page.get_by_role("dialog", name="New Account", exact=True)
    await account_dialog.get_by_placeholder("e.g., Cash on Hand").fill(ACCOUNT_NAME)
    await account_dialog.get_by_label("Type *", exact=True).select_option("ASSET")
    await account_dialog.get_by_label("Currency *", exact=True).select_option(CURRENCY)
    async with page.expect_response(
        lambda response: response.url.rstrip("/").endswith("/api/accounts")
        and response.request.method == "POST"
    ) as pending:
        await account_dialog.get_by_role(
            "button", name="Create Account", exact=True
        ).click()
    created = await pending.value
    assert created.status == 201, await created.text()
    account_id = (await created.json())["id"]
    record_property("browser_created_account_id", account_id)
    await expect(account_dialog).not_to_be_visible()

    # Before the entry, the balance sheet holds no balance for the account.
    before = await _balance_sheet(page, OPENING_DATE)
    before_lines = _lines_named(before["assets"], ACCOUNT_NAME)
    assert [Decimal(line["amount"]) for line in before_lines] == [ZERO]
    assert _lines_named(before["equity"], OFFSET_ACCOUNT_NAME) == []

    # Record the opening balance through the browser dialog. The readiness
    # banner holds a second button with the same name when it shows. Scope the
    # click to the Accounts page header so the match stays unambiguous.
    page_header = page.locator(".page-header").filter(
        has=page.get_by_role("heading", name="Accounts", exact=True)
    )
    await page_header.get_by_role(
        "button", name="Set opening balances", exact=True
    ).click()
    balance_dialog = page.get_by_role("dialog", name="Set opening balances", exact=True)
    await expect(balance_dialog).to_be_visible()
    await balance_dialog.get_by_label("As-of date *", exact=True).fill(OPENING_DATE)
    await balance_dialog.get_by_label(f"Opening balance for {ACCOUNT_NAME}").fill(
        OPENING_INPUT
    )
    async with page.expect_response(
        lambda response: "/api/accounts/opening-balances" in response.url
        and response.request.method == "POST"
    ) as pending:
        await balance_dialog.get_by_role(
            "button", name="Record opening balances", exact=True
        ).click()
    recorded = await pending.value
    assert recorded.status == 201, await recorded.text()
    await expect(balance_dialog).not_to_be_visible()

    # The balance sheet on the opening date shows the account line and the
    # Opening Balance Equity offset. Both equal the fixture constant.
    after = await _balance_sheet(page, OPENING_DATE)
    asset_lines = _lines_named(after["assets"], ACCOUNT_NAME)
    assert [Decimal(line["amount"]) for line in asset_lines] == [EXPECTED_OPENING]
    offset_lines = _lines_named(after["equity"], OFFSET_ACCOUNT_NAME)
    assert [Decimal(line["amount"]) for line in offset_lines] == [EXPECTED_OPENING]
    assert Decimal(after["total_assets"]) == EXPECTED_OPENING
    assert Decimal(after["total_liabilities"]) == ZERO
    assert Decimal(after["total_equity"]) == EXPECTED_OPENING

    # The balance sheet on the opening date holds the entry, so the entry is not
    # later than that date. The balance sheet on the day before holds no
    # balance, so the entry is not earlier than that date.
    day_before = (date.fromisoformat(OPENING_DATE) - timedelta(days=1)).isoformat()
    earlier = await _balance_sheet(page, day_before)
    assert [
        Decimal(line["amount"])
        for line in _lines_named(earlier["assets"], ACCOUNT_NAME)
    ] == [ZERO]

    # The accounts page shows the recorded balance on the account row.
    row = page.get_by_test_id(f"account-row-{account_id}")
    await expect(row).to_contain_text(ACCOUNT_NAME)
    await expect(row).to_contain_text(f"{EXPECTED_OPENING:,.2f}")
    checkpoint(record_property, "U5")
