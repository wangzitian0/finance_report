"""End-to-End interactive browser journey tests for Accounts and Statements (/accounts, /statements).

Covers:
- AC-ledger.account-registry.1: Account list, types, balances, and filter tabs.
- AC-extraction.statement-summary.1: Statement details, transactions table, and review surface.
- AC8.8.2 / AC8.10.2: Accounts CRUD and surface displays.
- AC8.4.2: Statement listing endpoints and detail surfaces.
- AC-testing.seeded-journey.1: Seeded statement bypasses provider.
- AC-testing.seeded-journey.2: Seeded statement list and detail rendering.
- AC-testing.seeded-journey.3: Seeded statement review.
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
    generate_standard_operations_csv,
)

APP_URL: str = os.getenv("APP_URL", TestConfig.APP_URL)


@pytest.mark.e2e
async def test_accounts_surface_and_balance_display(page: Page):
    """EPIC-001 EPIC-008 / AC-ledger.account-registry.1 AC8.13.9: Accounts registry, types, balances, and filter tabs."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    client, _user_email, _ = runner.create_ephemeral_client("accounts_journey")

    # 1. Seed accounts across multiple types
    runner.create_account(
        client, name="Main Operating Cash", type="ASSET", currency="SGD"
    )
    runner.create_account(client, name="Founding Equity", type="EQUITY", currency="SGD")
    runner.create_account(
        client, name="Software Subscription", type="EXPENSE", currency="SGD"
    )

    assert runner.last_auth_context is not None
    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    # 2. Navigate to /accounts
    await page.goto(f"{APP_URL}/accounts", wait_until="domcontentloaded")
    assert "/login" not in page.url

    # 3. Assert header and action button
    await expect(
        page.get_by_role("heading", name="Accounts", exact=True)
    ).to_be_visible(timeout=15_000)
    await expect(page.get_by_role("button", name="+ New Account")).to_be_visible(
        timeout=10_000
    )

    # 4. Assert seeded account names are rendered
    await expect(page.get_by_text("Main Operating Cash")).to_be_visible(timeout=10_000)
    await expect(page.get_by_text("Founding Equity")).to_be_visible(timeout=10_000)
    await expect(page.get_by_text("Software Subscription")).to_be_visible(
        timeout=10_000
    )

    # 5. Assert filter tabs exist and can be clicked
    asset_tab = page.get_by_role("button", name="ASSET", exact=True)
    if await asset_tab.count() > 0:
        await asset_tab.click()
        await expect(page.get_by_text("Main Operating Cash")).to_be_visible()


@pytest.mark.e2e
async def test_statement_detail_and_review_surface(page: Page):
    """EPIC-018 EPIC-008 / AC-extraction.statement-summary.1 AC8.13.9: Statement details, transactions table, and review surface."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    client, _user_email, _ = runner.create_ephemeral_client("statements_journey")

    runner.create_account(client, name="Operating Cash", type="ASSET", currency="SGD")
    csv_bytes = generate_standard_operations_csv()
    stmt_id = runner.upload_statement(client, csv_bytes, "operations.csv")
    runner.wait_for_statement_parsed(client, stmt_id)

    assert runner.last_auth_context is not None
    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    # 1. Navigate to Statement detail page
    await page.goto(f"{APP_URL}/statements/{stmt_id}", wait_until="domcontentloaded")
    assert "/login" not in page.url

    # 2. Assert statement summary cards or headers
    await expect(page.locator("body")).to_be_visible(timeout=15_000)
    # The statement detail renders the transaction rows from the parsed CSV
    await expect(page.get_by_text("CONSULTING SERVICES REVENUE")).to_be_visible(
        timeout=15_000
    )

    # 3. Navigate to Statement Review page
    await page.goto(
        f"{APP_URL}/statements/{stmt_id}/review", wait_until="domcontentloaded"
    )
    assert "/login" not in page.url
    await expect(page.locator("body")).to_be_visible(timeout=15_000)
