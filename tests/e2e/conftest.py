"""
Global pytest fixtures and configuration for Finance Report E2E tests.
"""

import json
import logging
import os
import sys
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional
import pytest
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestConfig:
    """Test configuration from environment variables."""

    APP_URL = os.getenv("APP_URL", "http://localhost:3000")
    TEST_ENV = os.getenv("TEST_ENV", "staging").lower()
    EXPECTED_SHA = os.getenv("EXPECTED_SHA")

    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "30000"))
    SLOW_MO = int(os.getenv("SLOW_MO", "0"))

    STORAGE_STATE_PATH = ROOT / "tests" / "e2e" / ".auth" / "state.json"


class AuthState:
    """Shared authentication state across test session."""

    user_id: Optional[str] = None
    email: Optional[str] = None
    access_token: Optional[str] = None
    password: Optional[str] = None


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root path."""
    return ROOT


@pytest.fixture(scope="session")
def config() -> TestConfig:
    """Provide test configuration."""
    return TestConfig()


@pytest.fixture(scope="session")
def event_loop():
    """Create and set event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def shared_auth_state() -> AsyncGenerator[AuthState, None]:
    """Create shared authentication state for all tests (runs once per session).

    This fixture:
    1. Registers ONE test user at session start
    2. Stores credentials in AuthState
    3. All tests reuse this user (10x faster than per-test registration)
    4. Cleans up user at session end
    """
    import httpx

    state = AuthState()
    unique_id = uuid.uuid4().hex[:8]
    state.email = f"e2e-session-{unique_id}@test.example.com"
    state.password = "E2ESessionPassword123!"

    logger.info(f"[SESSION SETUP] Creating shared test user: {state.email}")

    api_url = TestConfig.APP_URL.rstrip("/")

    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{api_url}/api/auth/register",
                json={"email": state.email, "password": state.password},
            )

            if response.status_code not in (200, 201):
                pytest.fail(
                    f"[SESSION SETUP] Failed to register shared user: {response.status_code} - {response.text}"
                )

            try:
                data = response.json()
            except ValueError as e:
                pytest.fail(
                    f"[SESSION SETUP] API returned invalid JSON: {response.text[:200]}... Error: {e}"
                )

            if not isinstance(data, dict):
                pytest.fail(
                    f"[SESSION SETUP] API returned non-dict: {type(data).__name__}"
                )

            state.user_id = data.get("id")
            state.access_token = data.get("access_token")

            if not state.user_id or not state.access_token:
                pytest.fail(
                    f"[SESSION SETUP] Registration response missing id or access_token. "
                    f"Got keys: {list(data.keys())}"
                )

            logger.info(f"[SESSION SETUP] Shared user created: {state.user_id}")

    except httpx.RequestError as e:
        pytest.fail(f"[SESSION SETUP] Failed to connect to backend: {e}")

    yield state

    logger.info(f"[SESSION TEARDOWN] Cleaning up shared test user: {state.user_id}")

    if state.user_id and state.access_token:
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                delete_response = await client.delete(
                    f"{api_url}/api/users/{state.user_id}",
                    headers={"Authorization": f"Bearer {state.access_token}"},
                )
                if delete_response.status_code in (200, 204):
                    logger.info(
                        f"[SESSION TEARDOWN] Shared user cleaned up successfully"
                    )
                elif delete_response.status_code == 404:
                    logger.debug(
                        f"[SESSION TEARDOWN] DELETE /api/users endpoint not found (status 404). "
                        f"Shared user {state.user_id} will remain in database."
                    )
                else:
                    logger.warning(
                        f"[SESSION TEARDOWN] Failed to cleanup shared user: status {delete_response.status_code}"
                    )
        except Exception as e:
            logger.debug(f"[SESSION TEARDOWN] Cleanup error (non-critical): {e}")


@pytest.fixture
async def browser() -> AsyncGenerator[Browser, None]:
    """Launch Playwright browser."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=TestConfig.HEADLESS,
            slow_mo=TestConfig.SLOW_MO,
        )
        yield browser
        await browser.close()


@pytest.fixture
async def context(browser: Browser) -> AsyncGenerator[BrowserContext, None]:
    """Create browser context."""
    context = await browser.new_context(
        ignore_https_errors=True,  # Allow self-signed certs
        viewport={"width": 1280, "height": 720},
        base_url=TestConfig.APP_URL,
    )
    yield context
    await context.close()


@pytest.fixture
async def page(context: BrowserContext) -> AsyncGenerator[Page, None]:
    """Create browser page."""
    page = await context.new_page()
    page.set_default_timeout(TestConfig.TIMEOUT_MS)
    yield page
    await page.close()


@pytest.fixture
async def authenticated_page(
    context: BrowserContext, shared_auth_state: AuthState
) -> AsyncGenerator[Page, None]:
    """Create browser page with authenticated user (using shared session auth).

    This fixture:
    1. Creates a new page
    2. Injects auth tokens from shared_auth_state into localStorage
    3. Navigates to dashboard to verify auth works

    PERFORMANCE: 10x faster than per-test registration because auth happens
    once per session via shared_auth_state fixture.

    Use this for tests that require authentication (e.g., /statements, /accounts).
    """
    page = await context.new_page()
    page.set_default_timeout(TestConfig.TIMEOUT_MS)

    logger.info(f"Setting up authenticated page for user: {shared_auth_state.user_id}")

    try:
        import jwt

        decoded = jwt.decode(
            shared_auth_state.access_token, options={"verify_signature": False}
        )
        exp_timestamp = decoded.get("exp")
        if exp_timestamp:
            time_until_expiry = exp_timestamp - datetime.now().timestamp()
            if time_until_expiry < 300:
                logger.warning(
                    f"Token expires in {time_until_expiry:.0f}s, test may fail for long runs"
                )
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Token expiration check failed: {e}")

    await context.add_init_script(
        f"""
        localStorage.setItem('finance_user_id', {json.dumps(str(shared_auth_state.user_id))});
        localStorage.setItem('finance_user_email', {json.dumps(shared_auth_state.email)});
        localStorage.setItem('finance_access_token', {json.dumps(shared_auth_state.access_token)});
    """
    )

    logger.info("Auth tokens injected into localStorage")

    await page.goto(f"{TestConfig.APP_URL}/dashboard")

    await page.wait_for_load_state("networkidle")
    if "/login" in page.url:
        pytest.fail(
            f"authenticated_page fixture failed: redirected to login. "
            f"Current URL: {page.url}. "
            f"Check if auth tokens are being properly injected."
        )

    logger.info("Authentication verified successfully")

    yield page
    await page.close()


@pytest.fixture
async def authenticated_page_unique(
    context: BrowserContext,
) -> AsyncGenerator[Page, None]:
    """Create browser page with UNIQUE test user (for isolation-critical tests).

    WARNING: This is SLOW (creates new user per test). Only use when you need
    complete isolation (e.g., testing user deletion, user-specific data).

    For most tests, use authenticated_page instead (10x faster).
    """
    import httpx

    page = await context.new_page()
    page.set_default_timeout(TestConfig.TIMEOUT_MS)

    unique_id = uuid.uuid4().hex[:8]
    test_email = f"e2e-unique-{unique_id}@test.example.com"
    test_password = "E2EUniquePassword123!"

    logger.info(f"Creating UNIQUE test user: {test_email}")

    api_url = TestConfig.APP_URL.rstrip("/")
    user_id = None
    access_token = None

    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                f"{api_url}/api/auth/register",
                json={"email": test_email, "password": test_password},
            )

            if response.status_code not in (200, 201):
                pytest.fail(
                    f"Failed to register test user: {response.status_code} - {response.text}"
                )

            # Validate JSON response
            try:
                data = response.json()
            except ValueError as e:
                pytest.fail(
                    f"API returned invalid JSON: {response.text[:200]}... Error: {e}"
                )

            # data is guaranteed to be set here if we didn't pytest.fail()
            if not isinstance(data, dict):
                pytest.fail(f"API returned non-dict: {type(data).__name__}")

            user_id = data.get("id")
            access_token = data.get("access_token")

            if not user_id or not access_token:
                pytest.fail(
                    f"Registration response missing id or access_token. "
                    f"Got keys: {list(data.keys())}"
                )

            logger.info(f"User registered successfully: {user_id}")

    except httpx.RequestError as e:
        pytest.fail(f"Failed to connect to backend for user registration: {e}")

    # Validate token expiration (optional, for long-running tests)
    try:
        import jwt

        decoded = jwt.decode(access_token, options={"verify_signature": False})
        exp_timestamp = decoded.get("exp")
        if exp_timestamp:
            time_until_expiry = exp_timestamp - datetime.now().timestamp()
            if time_until_expiry < 300:  # Less than 5 minutes
                logger.warning(
                    f"Token expires in {time_until_expiry:.0f}s, test may fail for long runs"
                )
    except ImportError:
        # PyJWT not installed, skip expiration check
        pass
    except Exception as e:
        # Token might not be JWT or decode failed - not critical, continue
        logger.debug(f"Token expiration check failed: {e}")

    # Inject auth tokens into localStorage before navigating
    # SECURITY: Use json.dumps() to prevent JavaScript injection
    await context.add_init_script(
        f"""
        localStorage.setItem('finance_user_id', {json.dumps(str(user_id))});
        localStorage.setItem('finance_user_email', {json.dumps(test_email)});
        localStorage.setItem('finance_access_token', {json.dumps(access_token)});
    """
    )

    logger.info("Auth tokens injected into localStorage")

    # Navigate to a protected page to verify auth works
    await page.goto(f"{TestConfig.APP_URL}/dashboard")

    # Verify we're NOT redirected to login
    await page.wait_for_load_state("networkidle")
    if "/login" in page.url:
        pytest.fail(
            f"authenticated_page fixture failed: redirected to login. "
            f"Current URL: {page.url}. Check if auth tokens are being properly injected."
        )

    logger.info("Authentication verified successfully")

    try:
        yield page
    finally:
        # Cleanup: Close page
        await page.close()

        # Best-effort cleanup: Attempt to delete test user
        # NOTE: DELETE /api/users/{id} endpoint may not exist yet
        # This is non-blocking - if it fails, we just log a warning
        if user_id and access_token:
            try:
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    delete_response = await client.delete(
                        f"{api_url}/api/users/{user_id}",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if delete_response.status_code in (200, 204):
                        logger.info(f"Test user {user_id} cleaned up successfully")
                    elif delete_response.status_code == 404:
                        logger.debug(
                            f"DELETE /api/users endpoint not found (status 404). "
                            f"Test user {user_id} will remain in database. "
                            f"Consider implementing user cleanup endpoint."
                        )
                    else:
                        logger.warning(
                            f"Failed to cleanup test user {user_id}: "
                            f"status {delete_response.status_code}"
                        )
            except Exception as e:
                logger.debug(f"User cleanup error (non-critical): {e}")
