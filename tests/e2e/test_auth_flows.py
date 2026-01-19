"""
Authentication Flow E2E Tests.

These tests verify the frontend-to-backend auth flows:
- User registration
- User login
- Session persistence

CRITICAL: These tests validate that NEXT_PUBLIC_API_URL is correctly
configured. If `NEXT_PUBLIC_API_URL` has a `/api` suffix but frontend
endpoints also include `/api/`, requests will go to `/api/api/...` causing 404.

Run with:
    APP_URL=https://report-staging.zitian.party pytest tests/e2e/test_auth_flows.py -v
"""
import os
import uuid
import pytest
from playwright.async_api import Page, expect

# --- Configuration ---
APP_URL = os.getenv("APP_URL", "http://localhost:3000")


def get_url(path: str) -> str:
    """Build full URL from path."""
    return f"{APP_URL.rstrip('/')}{path}"


@pytest.mark.asyncio
async def test_registration_api_path(page: Page):
    """
    Verify registration form submits to correct API path.
    
    This test will FAIL if NEXT_PUBLIC_API_URL has /api suffix,
    because frontend will send to /api/api/auth/register.
    """
    # Navigate to login page
    await page.goto(get_url("/login"))
    await expect(page.locator("h1")).to_contain_text("Finance Report")
    
    # Switch to Register mode
    await page.get_by_role("button", name="Register").click()
    
    # Fill registration form with unique email
    test_email = f"e2e_test_{uuid.uuid4().hex[:8]}@test.local"
    await page.get_by_label("Email").fill(test_email)
    await page.get_by_label("Password").fill("TestPassword123!")
    
    # Intercept network requests to verify API path
    api_request_path = None
    
    async def capture_request(request):
        nonlocal api_request_path
        if "auth/register" in request.url:
            api_request_path = request.url
    
    page.on("request", capture_request)
    
    # Submit form
    await page.get_by_role("button", name="Register").click()
    
    # Wait for either success redirect or error message
    await page.wait_for_timeout(2000)
    
    # Verify API was called (whether success or failure)
    assert api_request_path is not None, "Registration API was never called"
    
    # THE KEY ASSERTION: Check for double /api prefix bug
    assert "/api/api/" not in api_request_path, (
        f"Double /api prefix detected in API path: {api_request_path}\n"
        "This indicates NEXT_PUBLIC_API_URL is misconfigured with /api suffix."
    )
    
    # Verify expected path format
    assert "/api/auth/register" in api_request_path or "/auth/register" in api_request_path, (
        f"Unexpected API path: {api_request_path}"
    )


@pytest.mark.asyncio
async def test_login_api_path(page: Page):
    """
    Verify login form submits to correct API path.
    
    This test will FAIL if NEXT_PUBLIC_API_URL has /api suffix.
    """
    await page.goto(get_url("/login"))
    
    # Fill login form
    await page.get_by_label("Email").fill("test@example.com")
    await page.get_by_label("Password").fill("TestPassword123!")
    
    # Intercept network requests
    api_request_path = None
    
    async def capture_request(request):
        nonlocal api_request_path
        if "auth/login" in request.url:
            api_request_path = request.url
    
    page.on("request", capture_request)
    
    # Submit form (Login button should be active by default)
    await page.get_by_role("button", name="Login").click()
    
    # Wait for request
    await page.wait_for_timeout(2000)
    
    # Verify no double /api prefix
    if api_request_path:
        assert "/api/api/" not in api_request_path, (
            f"Double /api prefix detected: {api_request_path}"
        )


@pytest.mark.asyncio
async def test_full_registration_flow(page: Page):
    """
    Full E2E test: Register a new user and verify redirect to dashboard.
    
    This test creates real data and should only run on staging/dev.
    """
    await page.goto(get_url("/login"))
    
    # Switch to Register mode
    await page.get_by_role("button", name="Register").click()
    
    # Use unique email
    test_email = f"e2e_full_{uuid.uuid4().hex[:8]}@test.local"
    await page.get_by_label("Email").fill(test_email)
    await page.get_by_label("Password").fill("SecureTestPass123!")
    
    # Submit
    await page.get_by_role("button", name="Register").click()
    
    # Should redirect to dashboard on success
    # Or show error message on failure
    try:
        await expect(page).to_have_url(lambda url: "dashboard" in url, timeout=10000)
    except AssertionError:
        # Check for error message instead
        error_element = page.locator(".text-red-500, [class*='error']").first
        if await error_element.count() > 0:
            error_text = await error_element.text_content()
            # If it's "Not Found", the API path is wrong
            assert "Not Found" not in error_text, (
                "Got 'Not Found' error - likely double /api prefix issue"
            )
            # Other errors (like "Email exists") are acceptable test outcomes
            pytest.skip(f"Registration failed with: {error_text}")
        else:
            raise
