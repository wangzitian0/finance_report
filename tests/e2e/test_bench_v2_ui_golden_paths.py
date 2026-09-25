"""End-to-End Browser verification of Bench V2 financial reporting scenarios.

Executes Bench V2 multi-period financial accounting scenarios against the live
application and bridges the resulting user tenant session directly into a Playwright
browser page, asserting that the rendered UI accurately reflects:
1. Case 1: 4-Month Rollforward Trend & Q1 3-Statement Articulation (Dashboard & Balance Sheet).
2. Case 3: Credit Card Liability Clearance & Non-P&L Repayment Zero Double-Counting (Income Statement & Balance Sheet).
3. Case 4: Multi-Currency Consolidated Balance Sheet with IAS 21 CTA Rendering (Balance Sheet in SGD & USD).
4. Case 5: Multi-Asset & Property Appraisal Net Worth Integration (Portfolio & Balance Sheet).
"""

from __future__ import annotations

import os
import pytest
from playwright.async_api import Page, expect

from tests.e2e.bench_ui_bridge import BenchUiBridge
from tests.e2e.conftest import TestConfig
from tools._lib.benchmarks.run_financial_scenario_benchmark import (
    ScenarioBenchmarkRunner,
    execute_case_1,
    execute_case_3,
    execute_case_4,
    execute_case_5,
)

APP_URL: str = os.getenv("APP_URL", TestConfig.APP_URL)


@pytest.mark.e2e
async def test_case_1_four_month_rollforward_ui(page: Page):
    """Case 1: Verify 4-month continuous rollforward & Q1 articulation on Dashboard and Balance Sheet UI."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    result = execute_case_1(runner)
    assert result.status == "PASS", f"Case 1 benchmark failed: {result.error_message}"
    assert runner.last_auth_context is not None, "Missing runner auth context"

    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    # 1. Dashboard: Verify 4-month final asset and net worth amounts
    await page.goto(f"{APP_URL}/dashboard", wait_until="domcontentloaded")
    assert "/login" not in page.url
    await expect(page.get_by_label("Dashboard analytics")).to_be_visible(timeout=15_000)

    # Assets & Net Worth cards should both reflect 24,200.00
    assets_card = page.locator(".card").filter(has_text="Total Assets")
    await expect(assets_card).to_contain_text("24,200.00", timeout=15_000)

    net_worth_card = page.locator(".card").filter(has_text="Net Worth")
    await expect(net_worth_card).to_contain_text("24,200.00", timeout=15_000)

    # 2. Balance Sheet: Verify Q1 checkpoint (as of 2025-03-31) articulation
    await page.goto(
        f"{APP_URL}/reports/balance-sheet?as_of_date=2025-03-31&currency=SGD",
        wait_until="domcontentloaded",
    )
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=15_000
    )
    await expect(page.locator("#assets")).to_contain_text("21,300.00", timeout=15_000)
    await expect(page.locator("#equity")).to_contain_text("15,450.75", timeout=15_000)
    await expect(page.get_by_text("Balance Equation Detail")).to_be_visible()
    await expect(
        page.locator(".card").filter(has_text="Balance Equation Detail")
    ).to_contain_text("5,849.25")
    await expect(page.get_by_text("Balanced")).to_be_visible()


@pytest.mark.e2e
async def test_case_3_credit_card_repayment_non_pnl_ui(page: Page):
    """Case 3: Verify credit card liability clearance and zero double-counting on UI."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    result = execute_case_3(runner)
    assert result.status == "PASS", f"Case 3 benchmark failed: {result.error_message}"
    assert runner.last_auth_context is not None

    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    # 1. Balance Sheet: Liabilities must be 0.00, cash assets 8,800.00
    await page.goto(
        f"{APP_URL}/reports/balance-sheet?as_of_date=2025-04-30&currency=SGD",
        wait_until="domcontentloaded",
    )
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=15_000
    )
    await expect(page.locator("#liabilities")).to_contain_text("0.00", timeout=15_000)
    await expect(page.locator("#assets")).to_contain_text("8,800.00", timeout=15_000)
    await expect(page.get_by_text("Balanced")).to_be_visible()

    # 2. Income Statement: Operating expenses strictly single-counted (1,200.00), not double counted
    await page.goto(
        f"{APP_URL}/reports/income-statement?start_date=2025-04-01&end_date=2025-04-30&currency=SGD",
        wait_until="domcontentloaded",
    )
    await expect(page.get_by_role("heading", name="Income Statement")).to_be_visible(
        timeout=15_000
    )
    await expect(
        page.locator(".card").filter(has_text="Total Expenses")
    ).to_contain_text("1,200.00", timeout=15_000)
    await expect(page.locator(".card").filter(has_text="Net Income")).to_contain_text(
        "-1,200.00", timeout=15_000
    )


@pytest.mark.e2e
async def test_case_4_multicurrency_cta_balance_sheet_ui(page: Page):
    """Case 4: Verify multi-currency consolidated balance sheet and IAS 21 CTA display on UI."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    result = execute_case_4(runner)
    assert result.status == "PASS", f"Case 4 benchmark failed: {result.error_message}"
    assert runner.last_auth_context is not None

    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    # 1. SGD Consolidated Balance Sheet: check CTA Adjustment element and Equation Delta
    await page.goto(
        f"{APP_URL}/reports/balance-sheet?as_of_date=2025-04-30&currency=SGD",
        wait_until="domcontentloaded",
    )
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=15_000
    )
    await expect(page.get_by_test_id("equation-detail-cta")).to_be_visible(
        timeout=15_000
    )
    await expect(page.get_by_text("Balanced")).to_be_visible()

    # 2. USD Consolidated Balance Sheet
    await page.goto(
        f"{APP_URL}/reports/balance-sheet?as_of_date=2025-04-30&currency=USD",
        wait_until="domcontentloaded",
    )
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=15_000
    )
    await expect(page.get_by_test_id("equation-detail-cta")).to_be_visible(
        timeout=15_000
    )
    await expect(page.get_by_text("Balanced")).to_be_visible()


@pytest.mark.e2e
async def test_case_5_multi_asset_portfolio_and_appraisal_ui(page: Page):
    """Case 5: Verify multi-asset equities and property appraisal on Portfolio and Balance Sheet UI."""
    runner = ScenarioBenchmarkRunner(base_url=APP_URL, timeout=120.0)
    result = execute_case_5(runner)
    assert result.status == "PASS", f"Case 5 benchmark failed: {result.error_message}"
    assert runner.last_auth_context is not None

    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, APP_URL
    )

    # 1. Portfolio: Verify AAPL and VT holdings are rendered
    await page.goto(f"{APP_URL}/portfolio", wait_until="domcontentloaded")
    assert "/login" not in page.url
    await expect(page.get_by_text("AAPL").first).to_be_visible(timeout=15_000)
    await expect(page.get_by_text("VT").first).to_be_visible(timeout=15_000)

    # 2. Balance Sheet: Verify property appraisal included
    await page.goto(
        f"{APP_URL}/reports/balance-sheet?as_of_date=2025-04-30&currency=USD&include_restricted=true",
        wait_until="domcontentloaded",
    )
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=15_000
    )
    await expect(page.get_by_text("Balanced")).to_be_visible()
