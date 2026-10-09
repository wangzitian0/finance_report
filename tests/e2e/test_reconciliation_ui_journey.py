"""End-to-End interactive browser journey tests for Reconciliation (/reconciliation).

Covers:
- AC-reconciliation.workbench.1: Workbench review queue and match statistics.
- AC-reconciliation.review-queue.1: Confidence tiers and disposition workflow.
- AC8.8.5 / AC8.10.5: Reconciliation API and workbench displays.
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
from tools._lib.benchmarks.statement_generators import (
    generate_standard_operations_csv,
)

APP_URL: str = os.getenv("APP_URL", TestConfig.APP_URL)


@pytest.mark.e2e
async def test_reconciliation_workbench_surface_and_navigation(
    authenticated_page: Page,
):
    """EPIC-004 EPIC-007 EPIC-008 / AC-reconciliation.workbench.1 AC8.13.9: Reconciliation workbench layout and studio navigation."""
    page = authenticated_page
    await page.goto(f"{APP_URL}/reconciliation", wait_until="domcontentloaded")
    assert "/login" not in page.url

    # 1. Assert workbench heading and analytics
    await expect(
        page.get_by_role("heading", name="Reconciliation Workbench", exact=True)
    ).to_be_visible(timeout=15_000)
    await expect(page.get_by_text("Match Rate")).to_be_visible(timeout=10_000)
    await expect(
        page.get_by_role("heading", name="Score Distribution", exact=True)
    ).to_be_visible(timeout=10_000)

    # 2. Navigate to Unmatched Transactions Studio
    await page.get_by_role("link", name="Unmatched Studio").click()
    await expect(
        page.get_by_role("heading", name="Unmatched Transactions", exact=True)
    ).to_be_visible(timeout=15_000)

    # 3. Return to Workbench
    await page.get_by_role("link", name="← Workbench").click()
    await expect(
        page.get_by_role("heading", name="Reconciliation Workbench", exact=True)
    ).to_be_visible(timeout=15_000)


@pytest.mark.e2e
async def test_reconciliation_review_queue_surface(authenticated_page: Page):
    """EPIC-007 EPIC-008 / AC-reconciliation.review-queue.1 AC8.13.9: Reconciliation dedicated review queue."""
    page = authenticated_page
    await page.goto(
        f"{APP_URL}/reconciliation/review-queue", wait_until="domcontentloaded"
    )
    assert "/login" not in page.url

    await expect(
        page.get_by_role("heading", name="Review Queue", exact=True)
    ).to_be_visible(timeout=15_000)
    await expect(page.locator("body")).to_be_visible()


@pytest.mark.e2e
async def test_reconciliation_unmatched_interactive_disposition(page: Page):
    """EPIC-007 EPIC-008 / AC-reconciliation.workbench.1 AC-reconciliation.review-queue.1: Interactive disposition drawer selection and posting."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    client, _user_email, _ = runner.create_ephemeral_client("recon_disposition")

    # 1. Create operating accounts
    runner.create_account(client, name="Operating Cash", type="ASSET", currency="SGD")
    runner.create_account(
        client, name="Office Supplies", type="EXPENSE", currency="SGD"
    )

    # 2. Upload CSV statement to generate unmatched transactions
    csv_bytes = generate_standard_operations_csv()
    stmt_id = runner.upload_statement(client, csv_bytes, "operations.csv")
    runner.wait_for_statement_parsed(client, stmt_id)

    assert runner.last_auth_context is not None
    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    # 3. Navigate to Unmatched Transactions
    await page.goto(
        f"{APP_URL}/reconciliation/unmatched", wait_until="domcontentloaded"
    )
    assert "/login" not in page.url

    await expect(
        page.get_by_role("heading", name="Unmatched Transactions", exact=True)
    ).to_be_visible(timeout=15_000)

    # 4. Assert that unmatched transaction list is populated
    txn_item = page.get_by_text("AWS CLOUD HOSTING AND SAAS")
    await expect(txn_item).to_be_visible(timeout=10_000)

    # 5. Click the transaction to activate Reviewed Disposition drawer
    await txn_item.click()
    await expect(
        page.get_by_role("heading", name="Reviewed Disposition", exact=True)
    ).to_be_visible()

    # 6. Fill Reviewed Disposition form: select Expense intent, select counter account, fill category and rationale
    intent_select = page.get_by_label("Economic intent")
    await intent_select.select_option(value="expense")

    counter_select = page.locator("#counter-account-select")
    await expect(counter_select).to_be_visible()
    await counter_select.select_option(label="Office Supplies · EXPENSE")

    category_input = page.locator('input[placeholder="For example, DINING or SALARY"]')
    await category_input.fill("OFFICE_EXPENSE")

    rationale_textarea = page.locator(
        'textarea[placeholder="What source evidence supports this decision?"]'
    )
    await rationale_textarea.fill("Approved IT cloud infrastructure expense")

    # 7. Click Confirm and Post
    confirm_btn = page.get_by_role("button", name="Confirm and Post")
    await expect(confirm_btn).to_be_enabled()
    await confirm_btn.click()

    # 8. Assert: success banner is rendered confirming posted reviewed entry
    await expect(page.get_by_text("Posted reviewed entry")).to_be_visible(
        timeout=15_000
    )
