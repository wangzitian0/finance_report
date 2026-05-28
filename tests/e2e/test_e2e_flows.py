"""
End-to-End Functional Flow Tests (Finance Report).

Covers:
- AC8.13.9: read-only route smoke for protected pages.
- AC16.12.11: reports page route smoke.
- AC8.10.8 / AC16.12.6 / AC1.7.1: user registration flow.
"""

import os
import uuid
import pytest
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, expect

# --- Configuration ---

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
AUTH_REDIRECT_TIMEOUT = 10000


def get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


async def wait_for_optional_login_redirect(page: Page) -> None:
    try:
        await page.wait_for_url("**/login", timeout=AUTH_REDIRECT_TIMEOUT)
    except PlaywrightTimeoutError:
        pass


async def assert_no_visible_error_page(page: Page) -> None:
    next_404 = page.locator("h1.next-error-h1", has_text="404")
    if await next_404.count() > 0:
        await expect(next_404.first()).not_to_be_visible()

    body_text = await page.locator("body").inner_text()
    assert "Internal Server Error" not in body_text


# --- Fixtures ---


@pytest.fixture(autouse=True)
async def setup_e2e(page: Page):
    """Common setup for all E2E tests."""
    # Could handle login here if implemented
    pass


# --- Tests ---


@pytest.mark.smoke
@pytest.mark.e2e
async def test_full_navigation(page: Page):
    """AC8.13.9: Verify main routes load or redirect to login without 500s."""
    pages = [
        "/dashboard",
        "/accounts",
        "/journal",
        "/statements",
        "/reconciliation",
        "/reports",
    ]

    for path in pages:
        await page.goto(get_url(path), wait_until="domcontentloaded")
        await wait_for_optional_login_redirect(page)

        # Since we are not logged in, we expect either the page or a redirect to login
        # We check that the body is visible and we didn't hit a 500 error.
        await expect(page.locator("body")).to_be_visible()

        # Allow being on the login page as a successful "protection" check
        if "/login" in page.url:
            continue

        # If not redirected, ensure no visible Next.js error page.
        await assert_no_visible_error_page(page)


@pytest.mark.e2e
async def test_reports_view(page: Page):
    """AC8.13.9 AC16.12.11: Reports page renders or redirects to login."""
    await page.goto(get_url("/reports"), wait_until="domcontentloaded")

    # Wait a moment for potential AuthGuard redirect
    await wait_for_optional_login_redirect(page)

    if "/login" in page.url:
        # If redirected to login, verify login page basic visibility
        await expect(page.locator("body")).to_be_visible()
        return

    await expect(page.get_by_text("Balance Sheet", exact=False).first).to_be_visible()


@pytest.mark.e2e
async def test_registration_flow(page: Page):
    """
    AC8.10.8 AC16.12.6 AC1.7.1

    User Registration Flow.
    Verifies that the API URL configuration is correct (no double /api/ issue).
    """
    await page.goto(get_url("/login"))

    # Verify we are on the login page
    await expect(page.locator("body")).to_be_visible()

    # Switch to Register tab - use .first to specify the tab button (not the bottom link)
    await page.get_by_role("button", name="Register").first.click()

    # Generate unique email for this test
    unique_email = f"e2e-test-{uuid.uuid4().hex[:8]}@example.com"
    test_password = "TestPassword123!"

    # Fill registration form
    await page.get_by_label("Email Address").fill(unique_email)
    await page.get_by_label("Password", exact=True).fill(test_password)

    # Submit and wait for response
    async with page.expect_response("**/api/auth/register") as response_info:
        await page.get_by_role("button", name="Create Account").click()

    response = await response_info.value

    # Verify successful registration (201 or 200 depending on implementation)
    assert response.status in [200, 201], (
        f"Registration failed with status {response.status}"
    )

    # Verify response contains user data (id and email)
    response_data = await response.json()
    assert "id" in response_data, "Response should contain user id"
    assert "access_token" in response_data, "Response should contain access token"

    # Verify we were redirected to dashboard
    await page.wait_for_url("**/dashboard", timeout=5000)
    assert "/dashboard" in page.url, "Should redirect to dashboard after registration"
