"""
E2E Auth Flow tests

These tests validate authentication flows from a UI perspective,
including registration, login, logout, and session management.
Tests simulate user interactions with authentication features.

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
    AC8.2.1: User registration flow
    GIVEN a new user visits the registration page
    WHEN they complete the registration form with valid data
    THEN they should be successfully registered and redirected to dashboard
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/auth/register")

    await page.fill("input[name='email']", "newuser@example.com")
    await page.fill("input[name='password']", "SecurePass123!")
    await page.fill("input[name='name']", "New User")

    await page.click("button[type='submit']")

    await page.wait_for_url("**/dashboard**")
    assert "dashboard" in page.url


@pytest.mark.e2e
async def test_login_flow(page):
    """
    AC8.2.3: Login with valid credentials
    GIVEN a registered user visits the login page
    WHEN they enter valid credentials
    THEN they should be logged in and redirected to dashboard
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        warnings.warn("Skipping E2E UI test: FRONTEND_URL not set", UserWarning)
        return

    await page.goto(f"{frontend_url}/auth/login")

    await page.fill("input[name='email']", "test@example.com")
    await page.fill("input[name='password']", "SecurePass123!")

    await page.click("button[type='submit']")

    await page.wait_for_url("**/dashboard**")
    assert "dashboard" in page.url


@pytest.mark.e2e
async def test_login_invalid_credentials(page):
    """
    AC8.2.4: Login with invalid credentials
    GIVEN a registered user visits the login page
    WHEN they enter invalid credentials
    THEN they should see an error message
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/auth/login")

    await page.fill("input[name='email']", "wrong@example.com")
    await page.fill("input[name='password']", "wrongpass")

    await page.click("button[type='submit']")

    error_element = await page.wait_for_selector(".error-message")
    assert await error_element.is_visible()


@pytest.mark.e2e
async def test_logout_flow(page):
    """
    AC8.2.5: Logout flow
    GIVEN a logged-in user clicks logout
    WHEN the logout completes
    THEN they should be redirected to login page
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/dashboard")

    await page.click("text=Logout")
    await page.click("button:has-text('Confirm')")

    await page.wait_for_url("**/login**")
    assert "login" in page.url


@pytest.mark.e2e
async def test_password_reset_flow(page):
    """
    AC8.2.6: Password reset flow
    GIVEN a user visits the password reset page
    WHEN they request a password reset with valid email
    THEN they should see confirmation message
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    await page.goto(f"{frontend_url}/auth/forgot-password")

    await page.fill("input[name='email']", "user@example.com")

    await page.click("button[type='submit']")

    confirmation = await page.wait_for_selector(".confirmation-message")
    assert await confirmation.is_visible()
