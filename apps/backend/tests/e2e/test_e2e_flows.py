"""
E2E Flow tests for UI-based user journeys

These tests validate complete user workflows from a UI perspective,
including navigation, registration, report viewing, and various status transitions.
Tests simulate user interactions across the application.

Prerequisites:
- Frontend running (set FRONTEND_URL env var)
- Backend running
- Playwright browsers installed

Run with:
    moon run :test -- --e2e
"""

import os

import pytest


@pytest.mark.e2e
async def test_registration_flow(page):
    """
    EPIC-001 EPIC-016 / AC8.2.1: New User Registration
    GIVEN a new user visits the registration page
    WHEN they complete the registration form with valid data
    THEN they should be successfully registered and redirected to Home
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/login")

    await page.fill("input[name='email']", "test@example.com")
    await page.fill("input[name='password']", "SecurePass123!")
    await page.fill("input[name='name']", "Test User")

    await page.click("button[type='submit']")

    await page.wait_for_url(lambda url: "/login" not in url)
    assert "/login" not in page.url


@pytest.mark.e2e
async def test_login_flow(page):
    """
    EPIC-001 EPIC-016 / AC8.2.1: Login flow
    GIVEN a registered user visits the login page
    WHEN they enter valid credentials
    THEN they should be logged in and redirected to Home
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/login")

    await page.fill("input[name='email']", "test@example.com")
    await page.fill("input[name='password']", "SecurePass123!")

    await page.click("button[type='submit']")

    await page.wait_for_url(lambda url: "/login" not in url)
    assert "/login" not in page.url


@pytest.mark.e2e
async def test_navigation_flow(page):
    """
    EPIC-001 EPIC-005 EPIC-016 / AC8.6.4: Report navigation
    GIVEN a logged-in user navigates through the application
    WHEN they access different sections
    THEN navigation should work smoothly without errors
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/")

    # EPIC-022: internal accounting modules live under the collapsed Advanced group.
    await page.click("button:has-text('Advanced')")
    await page.click("text=Accounts")
    await page.wait_for_url("**/accounts**")
    assert "accounts" in page.url

    # Advanced auto-expands while on an advanced route, so Journal is reachable.
    await page.click("text=Journal")
    await page.wait_for_url("**/journal**")
    assert "journal" in page.url

    await page.click("text=Reports")
    await page.wait_for_url("**/reports**")
    assert "reports" in page.url


@pytest.mark.e2e
async def test_report_viewing_flow(page):
    """
    EPIC-005 / AC8.6.1: View Balance Sheet
    GIVEN a logged-in user navigates to reports
    WHEN they select and view a balance sheet
    THEN the balance sheet should display correctly with proper formatting
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/reports")

    await page.click("text=Balance Sheet")

    await page.wait_for_selector(".balance-sheet-container")

    assert await page.is_visible("text=Assets")
    assert await page.is_visible("text=Liabilities")
    assert await page.is_visible("text=Equity")


@pytest.mark.e2e
async def test_income_statement_viewing_flow(page):
    """
    EPIC-005 / AC8.6.2: View Income Statement
    GIVEN a logged-in user navigates to reports
    WHEN they select and view an income statement
    THEN the income statement should display correctly
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/reports")

    await page.click("text=Income Statement")

    await page.wait_for_selector(".income-statement-container")

    assert await page.is_visible("text=Income")
    assert await page.is_visible("text=Expenses")
    assert await page.is_visible("text=Net Income")


@pytest.mark.e2e
async def test_cash_flow_viewing_flow(page):
    """
    EPIC-005 / AC8.6.3: View Cash Flow Report
    GIVEN a logged-in user navigates to reports
    WHEN they select and view a cash flow report
    THEN the cash flow report should display correctly
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/reports")

    await page.click("text=Cash Flow")

    await page.wait_for_selector(".cash-flow-container")

    assert await page.is_visible("text=Operating")
    assert await page.is_visible("text=Investing")
    assert await page.is_visible("text=Financing")
