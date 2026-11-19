from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.async_api import Page, expect

from tests.e2e._journey_helpers import assert_pinned_via_page, get_url
from tests.e2e.journey_checkpoint import checkpoint

ACCOUNT_NAME = "U5 Opening Proof Savings"
OFFSET_ACCOUNT_NAME = "Opening Balance Equity"
CURRENCY = "SGD"
OPENING_DATE = "2025-12-31"
EXPECTED_OPENING = Decimal("1234.56")
ZERO = Decimal("0")


def _lines_named(lines: list[dict], name: str) -> list[dict]:
    return [line for line in lines if line["name"] == name]


async def _balance_sheet(page: Page, as_of_date: str) -> dict:
    resp = await page.request.get(
        get_url("/api/reports/balance-sheet"),
        params={"as_of_date": as_of_date, "currency": CURRENCY},
    )
    assert resp.status == 200, await resp.text()
    return await resp.json()


@pytest.mark.e2e
@pytest.mark.journey
async def test_opening_balance_recorded_through_browser(
    authenticated_page_unique: Page, record_property
) -> None:
    page = authenticated_page_unique
    await assert_pinned_via_page(page, record_property)

    await page.goto(get_url("/settings?tab=accounts"))
    await page.get_by_role("button", name="Add Account", exact=True).click()
    dialog = page.get_by_role("dialog", name="New Account", exact=True)
    await dialog.get_by_placeholder("e.g., Cash on Hand").fill(ACCOUNT_NAME)
    await dialog.get_by_label("Type *", exact=True).select_option("ASSET")
    await dialog.get_by_label("Currency *", exact=True).select_option(CURRENCY)
    async with page.expect_response(
        lambda r: r.url.rstrip("/").endswith("/api/accounts")
        and r.request.method == "POST"
    ) as pending:
        await dialog.get_by_role("button", name="Create Account", exact=True).click()
    created = await pending.value
    assert created.status == 201, await created.text()
    account_id = (await created.json())["id"]
    record_property("browser_created_account_id", account_id)
    await expect(dialog).not_to_be_visible()

    before = await _balance_sheet(page, OPENING_DATE)
    assert [
        Decimal(ln["amount"]) for ln in _lines_named(before["assets"], ACCOUNT_NAME)
    ] == [ZERO]
    assert _lines_named(before["equity"], OFFSET_ACCOUNT_NAME) == []

    await (
        page.locator(".page-header")
        .filter(has=page.get_by_role("heading", name="Accounts", exact=True))
        .get_by_role("button", name="Set opening balances", exact=True)
        .click()
    )
    balance_dialog = page.get_by_role("dialog", name="Set opening balances", exact=True)
    await expect(balance_dialog).to_be_visible()
    await balance_dialog.get_by_label("As-of date *", exact=True).fill(OPENING_DATE)
    await balance_dialog.get_by_label(f"Opening balance for {ACCOUNT_NAME}").fill(
        "1234.56"
    )
    async with page.expect_response(
        lambda r: "/api/accounts/opening-balances" in r.url
        and r.request.method == "POST"
    ) as pending:
        await balance_dialog.get_by_role(
            "button", name="Record opening balances", exact=True
        ).click()
    assert (await pending.value).status == 201
    await expect(balance_dialog).not_to_be_visible()

    after = await _balance_sheet(page, OPENING_DATE)
    assert [
        Decimal(ln["amount"]) for ln in _lines_named(after["assets"], ACCOUNT_NAME)
    ] == [EXPECTED_OPENING]
    assert [
        Decimal(ln["amount"])
        for ln in _lines_named(after["equity"], OFFSET_ACCOUNT_NAME)
    ] == [EXPECTED_OPENING]
    assert (
        Decimal(after["total_assets"]) == EXPECTED_OPENING
        and Decimal(after["total_liabilities"]) == ZERO
        and Decimal(after["total_equity"]) == EXPECTED_OPENING
    )
    earlier = await _balance_sheet(
        page, (date.fromisoformat(OPENING_DATE) - timedelta(days=1)).isoformat()
    )
    assert [
        Decimal(ln["amount"]) for ln in _lines_named(earlier["assets"], ACCOUNT_NAME)
    ] == [ZERO]
    row = page.get_by_test_id(f"account-row-{account_id}")
    await expect(row).to_contain_text(ACCOUNT_NAME)
    await expect(row).to_contain_text(f"{EXPECTED_OPENING:,.2f}")
    checkpoint(record_property, "U5")
