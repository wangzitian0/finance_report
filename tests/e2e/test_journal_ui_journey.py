from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Page, expect

from tests.e2e._journey_helpers import get_url, setup_runner_page

MODAL_CLOSE_TIMEOUT_MS = 30000


async def _open_new_entry_modal(
    page: Page,
    prefix: str,
    *,
    description: str,
    rationale: str,
    line1_amount: str,
    line2_amount: str,
) -> None:
    await setup_runner_page(
        page, prefix, (("Operating Cash", "ASSET"), ("Owner Capital", "EQUITY"))
    )
    await page.goto(get_url("/journal"), wait_until="domcontentloaded")
    assert "/login" not in page.url
    await expect(
        page.get_by_role("heading", name="Journal Entries", exact=True)
    ).to_be_visible(timeout=15000)
    await page.get_by_role("button", name="New Entry").click()
    await expect(
        page.get_by_role("heading", name="New Journal Entry", exact=True)
    ).to_be_visible(timeout=10000)
    await page.locator('input[placeholder="Description"]').fill(description)
    await page.locator('input[placeholder="Why this entry is correct"]').fill(rationale)
    line1_acc = page.get_by_role("combobox", name="Line 1 account")
    await expect(line1_acc).to_be_visible()
    await line1_acc.select_option(label="Operating Cash")
    await page.get_by_role("spinbutton", name="Line 1 amount").fill(line1_amount)
    await page.get_by_role("combobox", name="Line 2 account").select_option(
        label="Owner Capital"
    )
    await page.get_by_role("spinbutton", name="Line 2 amount").fill(line2_amount)


@pytest.mark.e2e
async def test_journal_unbalanced_entry_falsification(page: Page) -> None:
    await _open_new_entry_modal(
        page,
        "journal_falsify",
        description="Imbalanced Test Entry",
        rationale="Testing validation gate",
        line1_amount="100.00",
        line2_amount="90.00",
    )
    await expect(page.get_by_text("⚠ Unbalanced or missing FX")).to_be_visible()
    await expect(page.get_by_role("button", name="Create Draft")).to_be_disabled()


@pytest.mark.e2e
async def test_journal_balanced_entry_creation_and_post(page: Page) -> None:
    memo_text = "Balanced Capital Injection"
    await _open_new_entry_modal(
        page,
        "journal_create",
        description=memo_text,
        rationale="Owner initial contribution",
        line1_amount="500.00",
        line2_amount="500.00",
    )
    await page.locator("#postImmediately").check()
    await expect(page.get_by_text("✓ Balanced in SGD")).to_be_visible()
    submit_btn = page.get_by_role("button", name="Create & Post")
    await expect(submit_btn).to_be_enabled()
    calls: list[str] = []

    async def _record(response) -> None:
        if "/api/" in response.url and response.request.method != "GET":
            try:
                body = (await response.text())[:200]
            except Exception as exc:
                body = f"<{type(exc).__name__}>"
            calls.append(
                f"{response.request.method} {response.url} -> {response.status} {body}"
            )

    page.on("response", lambda r: asyncio.ensure_future(_record(r)))
    await submit_btn.click()
    try:
        await expect(
            page.get_by_role("heading", name="New Journal Entry", exact=True)
        ).not_to_be_visible(timeout=MODAL_CLOSE_TIMEOUT_MS)
    except AssertionError as exc:
        raise AssertionError(
            f"Journal modal stayed open {MODAL_CLOSE_TIMEOUT_MS}ms. Calls: {calls}. Alerts: {await page.locator('[role="alert"], [role="status"]').all_inner_texts()}"
        ) from exc
    await expect(page.get_by_text(memo_text)).to_be_visible(timeout=15000)
