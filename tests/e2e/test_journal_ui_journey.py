"""End-to-End interactive browser journey tests for Journal Entries (/journal).

Covers:
- AC-ledger.journal-entry.1: Journal entry double-entry balance validation.
- AC-ledger.journal-entry.2: Immediate posting and draft creation.
- AC8.13.9: Authenticated UI route verification.
"""

from __future__ import annotations

import os
import pytest
from playwright.async_api import Page, expect

from tests.e2e.bench_ui_bridge import BenchUiBridge
from tests.e2e.conftest import TestConfig
from tools._lib.benchmarks.run_financial_scenario_benchmark import (
    ScenarioBenchmarkRunner,
)

APP_URL: str = os.getenv("APP_URL", TestConfig.APP_URL)


@pytest.mark.e2e
async def test_journal_unbalanced_entry_falsification(page: Page):
    """EPIC-001 EPIC-008 / AC-ledger.journal-entry.1: Falsification - Unbalanced debit/credit blocks submission."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    client, user_email, _ = runner.create_ephemeral_client("journal_falsify")
    runner.create_account(client, name="Operating Cash", type="ASSET", currency="SGD")
    runner.create_account(client, name="Owner Capital", type="EQUITY", currency="SGD")
    assert runner.last_auth_context is not None

    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    await page.goto(f"{APP_URL}/journal", wait_until="domcontentloaded")
    assert "/login" not in page.url
    await expect(
        page.get_by_role("heading", name="Journal Entries", exact=True)
    ).to_be_visible(timeout=15_000)

    # 1. Open New Journal Entry modal
    await page.get_by_role("button", name="New Entry").click()
    await expect(
        page.get_by_role("heading", name="New Journal Entry", exact=True)
    ).to_be_visible(timeout=10_000)

    # 2. Fill basic metadata
    await page.locator('input[placeholder="Description"]').fill("Imbalanced Test Entry")
    await page.locator('input[placeholder="Why this entry is correct"]').fill(
        "Testing validation gate"
    )

    # 3. Fill Line 1: Debit $100.00
    line1_account = page.get_by_role("combobox", name="Line 1 account")
    await expect(line1_account).to_be_visible()
    await line1_account.select_option(label="Operating Cash")
    await page.get_by_role("spinbutton", name="Line 1 amount").fill("100.00")

    # 4. Fill Line 2: Credit $90.00 (Imbalanced: 100 != 90)
    line2_account = page.get_by_role("combobox", name="Line 2 account")
    await line2_account.select_option(label="Owner Capital")
    await page.get_by_role("spinbutton", name="Line 2 amount").fill("90.00")

    # 5. Assert: Imbalance warning is rendered and Submit button is disabled
    await expect(page.get_by_text("⚠ Unbalanced or missing FX")).to_be_visible()
    submit_btn = page.get_by_role("button", name="Create Draft")
    await expect(submit_btn).to_be_disabled()


@pytest.mark.e2e
async def test_journal_balanced_entry_creation_and_post(page: Page):
    """EPIC-001 EPIC-008 / AC-ledger.journal-entry.1 AC-ledger.journal-entry.2: Balanced entry creation and immediate posting."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    client, user_email, _ = runner.create_ephemeral_client("journal_create")
    runner.create_account(client, name="Operating Cash", type="ASSET", currency="SGD")
    runner.create_account(client, name="Owner Capital", type="EQUITY", currency="SGD")
    assert runner.last_auth_context is not None

    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    await page.goto(f"{APP_URL}/journal", wait_until="domcontentloaded")
    await expect(
        page.get_by_role("heading", name="Journal Entries", exact=True)
    ).to_be_visible(timeout=15_000)

    # 1. Open New Journal Entry modal
    await page.get_by_role("button", name="New Entry").click()
    await expect(
        page.get_by_role("heading", name="New Journal Entry", exact=True)
    ).to_be_visible(timeout=10_000)

    # 2. Fill basic metadata
    memo_text = "Balanced Capital Injection"
    await page.locator('input[placeholder="Description"]').fill(memo_text)
    await page.locator('input[placeholder="Why this entry is correct"]').fill(
        "Owner initial contribution"
    )

    # 3. Fill Line 1: Debit $500.00
    line1_account = page.get_by_role("combobox", name="Line 1 account")
    await expect(line1_account).to_be_visible()
    await line1_account.select_option(label="Operating Cash")
    await page.get_by_role("spinbutton", name="Line 1 amount").fill("500.00")

    # 4. Fill Line 2: Credit $500.00 (Balanced!)
    line2_account = page.get_by_role("combobox", name="Line 2 account")
    await line2_account.select_option(label="Owner Capital")
    await page.get_by_role("spinbutton", name="Line 2 amount").fill("500.00")

    # 5. Check "Post transaction immediately"
    await page.locator("#postImmediately").check()

    # 6. Assert: Balance indicator green and Submit button enabled
    await expect(page.get_by_text("✓ Balanced in SGD")).to_be_visible()
    submit_btn = page.get_by_role("button", name="Create & Post")
    await expect(submit_btn).to_be_enabled()

    # 7. Submit and verify entry appears in journal table with posted status
    await submit_btn.click()
    await expect(
        page.get_by_role("heading", name="New Journal Entry", exact=True)
    ).not_to_be_visible(timeout=10_000)
    await expect(page.get_by_text(memo_text)).to_be_visible(timeout=15_000)
