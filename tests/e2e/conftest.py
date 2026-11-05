"""
Global pytest fixtures and configuration for Finance Report E2E tests.
"""

import asyncio
import json
import logging
import os
import re
import sys
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path

import pytest
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from common.testing.e2e_rate_limit import (
    RateLimitHit,
    fail_report_for_rate_limits,
    record_rate_limit_response,
)
from tests.e2e.auth_cookie import (
    build_auth_cookie,
    redact_playwright_auth_headers,
)
from tests.e2e.critical_skip_gate import (
    CRITICAL_MARKER,
    critical_skip_failure_message,
    should_convert_skip_to_failure,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGE_TEXT_MAX_BYTES = 4096
_NODEID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_nodeid(nodeid: str) -> str:
    """Convert a pytest nodeid into a safe single directory name (#2745)."""
    sanitized = _NODEID_UNSAFE_RE.sub("__", nodeid.strip()).strip("._-")
    return sanitized or "unknown_test"


def _failure_artifact_dir(item: object) -> Path:
    """Return the failure diagnostic directory for ``item`` (#2745)."""
    root = Path(
        os.getenv("E2E_FAILURE_ARTIFACT_DIR")
        or (ROOT / "test-results" / "e2e-failures")
    )
    nodeid = str(getattr(item, "nodeid", "unknown_test"))
    return root / _sanitize_nodeid(nodeid)


def _truncate_utf8_bytes(text: str, max_bytes: int = PAGE_TEXT_MAX_BYTES) -> str:
    """Truncate ``text`` to at most ``max_bytes`` UTF-8 bytes without splitting codepoints."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


async def _read_visible_body_text(page: object) -> str:
    """Read visible body text from ``page`` with fallback to ``document.body.innerText`` (#2745)."""
    locator_fn = getattr(page, "locator", None)
    if callable(locator_fn):
        try:
            body = locator_fn("body")
            inner_text_fn = getattr(body, "inner_text", None)
            if callable(inner_text_fn):
                text = await inner_text_fn(timeout=2000)
                if isinstance(text, str):
                    return text
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"body.inner_text() fallback triggered: {exc}")

    evaluate_fn = getattr(page, "evaluate", None)
    if callable(evaluate_fn):
        try:
            text = await evaluate_fn(
                "() => (document && document.body && document.body.innerText) || ''"
            )
            if isinstance(text, str):
                return text
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"document.body.innerText fallback failed: {exc}")
    return ""


async def _capture_page_failure_diagnostics(
    item: object, page: object | None = None
) -> Path | None:
    """Write ``screenshot.png``, ``page-text.txt``, and ``page-errors.txt`` on UI test failure (#2745)."""
    if getattr(item, "_e2e_diagnostics_captured", False):
        return getattr(item, "_e2e_diagnostics_dir", None)

    pages: list[object] = list(getattr(item, "_e2e_pages", []))
    target_page = page
    if target_page is None:
        for candidate in reversed(pages):
            is_closed_fn = getattr(candidate, "is_closed", None)
            closed = is_closed_fn() if callable(is_closed_fn) else False
            if not closed:
                target_page = candidate
                break
        if target_page is None and pages:
            target_page = pages[-1]

    if target_page is None:
        return None

    setattr(item, "_e2e_diagnostics_captured", True)
    artifact_dir = _failure_artifact_dir(item)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    setattr(item, "_e2e_diagnostics_dir", artifact_dir)

    screenshot_path = artifact_dir / "screenshot.png"
    page_text_path = artifact_dir / "page-text.txt"
    page_errors_path = artifact_dir / "page-errors.txt"

    screenshot_fn = getattr(target_page, "screenshot", None)
    if callable(screenshot_fn):
        try:
            data = await screenshot_fn(path=str(screenshot_path), full_page=True)
            if not screenshot_path.exists() and isinstance(data, (bytes, bytearray)):
                screenshot_path.write_bytes(bytes(data))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to capture E2E failure screenshot: {exc}")

    raw_body_text = await _read_visible_body_text(target_page)
    scrubbed_body_text = redact_playwright_auth_headers(raw_body_text)
    bounded_body_text = _truncate_utf8_bytes(scrubbed_body_text, PAGE_TEXT_MAX_BYTES)
    page_text_path.write_text(bounded_body_text, encoding="utf-8")

    diagnostic_errors: list[str] = list(getattr(item, "_e2e_diagnostic_errors", []))
    scrubbed_errors = redact_playwright_auth_headers("\n".join(diagnostic_errors))
    page_errors_path.write_text(scrubbed_errors, encoding="utf-8")
    return artifact_dir


def _attach_page_diagnostics(item: object, page: object) -> None:
    """Attach console/pageerror listeners and close-time failure capture to ``page`` (#2745)."""
    pages: list[object] = getattr(item, "_e2e_pages", None)
    if pages is None:
        pages = []
        setattr(item, "_e2e_pages", pages)
    if page not in pages:
        pages.append(page)

    diagnostic_errors: list[str] = getattr(item, "_e2e_diagnostic_errors", None)
    if diagnostic_errors is None:
        diagnostic_errors = []
        setattr(item, "_e2e_diagnostic_errors", diagnostic_errors)

    on_fn = getattr(page, "on", None)
    if callable(on_fn):

        def _on_page_console(msg: object) -> None:
            msg_type = getattr(msg, "type", None)
            if callable(msg_type):
                msg_type = msg_type()
            if msg_type == "error":
                text = getattr(msg, "text", "")
                if callable(text):
                    text = text()
                text_str = str(text)
                if not _is_benign(text_str):
                    entry = f"console.error: {text_str}"
                    if entry not in diagnostic_errors:
                        diagnostic_errors.append(entry)

        def _on_page_error(err: object) -> None:
            text_str = str(getattr(err, "error", err))
            if not _is_benign(text_str):
                entry = f"pageerror: {text_str}"
                if entry not in diagnostic_errors:
                    diagnostic_errors.append(entry)

        on_fn("console", _on_page_console)
        on_fn("pageerror", _on_page_error)

    orig_close = getattr(page, "close", None)
    if callable(orig_close) and not getattr(page, "_e2e_close_wrapped", False):

        async def _wrapped_page_close(*args, **kwargs):
            if sys.exc_info()[0] is not None or getattr(
                item, "_e2e_test_failed", False
            ):
                await _capture_page_failure_diagnostics(item, page)
            return await orig_close(*args, **kwargs)

        try:
            setattr(page, "close", _wrapped_page_close)
            setattr(page, "_e2e_close_wrapped", True)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Could not wrap page.close: {exc}")


class TestConfig:
    """Test configuration from environment variables."""

    APP_URL = (
        os.getenv("APP_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000"
    )
    TEST_ENV = os.getenv("TEST_ENV", "staging").lower()
    EXPECTED_SHA = os.getenv("EXPECTED_SHA")

    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "30000"))
    SLOW_MO = int(os.getenv("SLOW_MO", "0"))

    STORAGE_STATE_PATH = ROOT / "tests" / "e2e" / ".auth" / "state.json"


def _strict_e2e_gates_enabled() -> bool:
    return os.getenv("STRICT_E2E_GATES", "").lower() in {"1", "true", "yes"}


def is_strict_or_ci() -> bool:
    """Return whether strict E2E gate mode or CI execution is active."""
    return _strict_e2e_gates_enabled() or os.getenv("CI") == "true"


def pytest_sessionstart(session):
    """EPIC-008: Fail-fast target environment handshake and freshness check."""
    if is_strict_or_ci():
        if TestConfig.TEST_ENV != "local":
            if not TestConfig.EXPECTED_SHA:
                pytest.exit(
                    "Fatal: EXPECTED_SHA must be explicitly set in CI, staging, and strict gate environments",
                    returncode=1,
                )
            health_url = f"{TestConfig.APP_URL.rstrip('/')}/api/health"
            try:
                import ssl
                import urllib.error
                import urllib.request

                ctx = ssl.create_default_context()
                if os.getenv("E2E_INSECURE_TLS", "").lower() in {"1", "true", "yes"}:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                req = urllib.request.Request(
                    health_url,
                    headers={"User-Agent": "E2E-Handshake/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10.0, context=ctx) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    live_sha = payload.get("git_sha")
                    if live_sha != TestConfig.EXPECTED_SHA:
                        pytest.exit(
                            f"Fatal: Stale target environment detected at {health_url}: expected SHA {TestConfig.EXPECTED_SHA}, but target serves {live_sha}",
                            returncode=1,
                        )
            except urllib.error.HTTPError as err:
                pytest.exit(
                    f"Fatal: Target health check failed with status {err.code} at {health_url}: {err.reason}",
                    returncode=1,
                )
            except Exception as exc:
                if isinstance(exc, pytest.exit.Exception):
                    raise
                pytest.exit(
                    f"Fatal: Could not connect to target environment at {health_url}: {exc}",
                    returncode=1,
                )


def format_ai_ocr_gate_failure(
    message: str,
    *,
    statement: dict | None = None,
    model: str | None = None,
) -> str:
    details: list[str] = []
    if model:
        details.append(f"model={model}")
    if statement:
        for key in (
            "id",
            "status",
            "validation_error",
            "confidence_score",
            "parsing_progress",
            "balance_validated",
        ):
            value = statement.get(key)
            if value not in (None, ""):
                details.append(f"{key}={value}")

    if not details:
        return message
    return f"{message}. Details: " + "; ".join(details)


def fail_or_skip_ai_ocr_gate(
    message: str,
    *,
    statement: dict | None = None,
    model: str | None = None,
) -> None:
    failure_message = format_ai_ocr_gate_failure(
        message,
        statement=statement,
        model=model,
    )
    if _strict_e2e_gates_enabled():
        pytest.fail(failure_message)
    pytest.skip(
        f"{failure_message} STRICT_E2E_GATES is not enabled for this environment."
    )


def _scrub_pytest_longrepr_node(node: object) -> bool:
    """Recursively scrub structured pytest longrepr nodes in place (#2662)."""
    scrubbed = False
    reprcrash = getattr(node, "reprcrash", None)
    if reprcrash is not None and isinstance(getattr(reprcrash, "message", None), str):
        reprcrash.message = redact_playwright_auth_headers(reprcrash.message)
        scrubbed = True

    reprtraceback = getattr(node, "reprtraceback", None)
    reprentries = getattr(reprtraceback, "reprentries", None)
    if isinstance(reprentries, list):
        for entry in reprentries:
            lines = getattr(entry, "lines", None)
            if isinstance(lines, list):
                entry.lines = [
                    redact_playwright_auth_headers(line)
                    if isinstance(line, str)
                    else line
                    for line in lines
                ]
                scrubbed = True
            entry_reprcrash = getattr(entry, "reprfileloc", None)
            if entry_reprcrash is not None and isinstance(
                getattr(entry_reprcrash, "message", None), str
            ):
                entry_reprcrash.message = redact_playwright_auth_headers(
                    entry_reprcrash.message
                )
                scrubbed = True

    chain = getattr(node, "chain", None)
    if isinstance(chain, list):
        for element in chain:
            if isinstance(element, tuple):
                for part in element:
                    if part is not None and _scrub_pytest_longrepr_node(part):
                        scrubbed = True
    return scrubbed


def _scrub_report_longrepr(report: object) -> None:
    """Ensure pytest report failure output contains zero unredacted auth headers/cookies (#2662)."""
    longrepr = getattr(report, "longrepr", None)
    if longrepr is None:
        return
    if isinstance(longrepr, str):
        setattr(report, "longrepr", redact_playwright_auth_headers(longrepr))
        return
    if (
        isinstance(longrepr, tuple)
        and len(longrepr) == 3
        and isinstance(longrepr[2], str)
    ):
        setattr(
            report,
            "longrepr",
            (longrepr[0], longrepr[1], redact_playwright_auth_headers(longrepr[2])),
        )
        return
    _scrub_pytest_longrepr_node(longrepr)
    longreprtext = getattr(report, "longreprtext", None)
    if isinstance(longreprtext, str):
        redacted_text = redact_playwright_auth_headers(longreprtext)
        if redacted_text != longreprtext:
            setattr(report, "longrepr", redacted_text)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if should_convert_skip_to_failure(
        strict_gates_enabled=_strict_e2e_gates_enabled(),
        skipped=report.skipped,
        has_critical_marker=item.get_closest_marker(CRITICAL_MARKER) is not None,
        when=report.when,
    ):
        report.outcome = "failed"
        report.longrepr = critical_skip_failure_message(item.nodeid)

    rate_limit_hits = getattr(item, "_e2e_rate_limit_hits", [])
    already_reported = getattr(item, "_e2e_rate_limit_reported", False)
    if (
        report.when in {"call", "teardown"}
        and rate_limit_hits
        and not already_reported
        and fail_report_for_rate_limits(report, rate_limit_hits)
    ):
        setattr(item, "_e2e_rate_limit_reported", True)

    _scrub_report_longrepr(report)

    if getattr(report, "failed", False) or getattr(report, "outcome", "") == "failed":
        setattr(item, "_e2e_test_failed", True)
        if not getattr(item, "_e2e_diagnostics_captured", False) and getattr(
            item, "_e2e_pages", None
        ):
            try:
                loop = asyncio.get_event_loop()
                if not loop.is_running() and not loop.is_closed():
                    loop.run_until_complete(_capture_page_failure_diagnostics(item))
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"makereport diagnostic capture skipped: {exc}")


class AuthState:
    """Shared authentication state across test session."""

    user_id: str | None = None
    email: str | None = None
    access_token: str | None = None
    password: str | None = None


def auth_cookie(access_token: str) -> dict[str, object]:
    try:
        return build_auth_cookie(TestConfig.APP_URL, access_token)
    except ValueError as exc:
        pytest.fail(str(exc))


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
                    f"[SESSION SETUP] Registration response missing id or access_token. Got keys: {list(data.keys())}"
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
                        "[SESSION TEARDOWN] Shared user cleaned up successfully"
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


# Content-agnostic browser correctness invariants (#1623): every e2e that drives
# a page transitively asserts the app did not throw an uncaught JS error and did
# not violate its own CSP on any visited page. This is NOT layout/style testing —
# it catches whole classes (a blocked analytics script, a crashing component)
# regardless of which page. Benign, environment-injected noise is allowlisted;
# a test that intentionally triggers an error opts out with
# @pytest.mark.allow_browser_errors.
_BENIGN_BROWSER_NOISE = (
    # Cloudflare edge-injects its insights beacon; not app-owned, not our CSP.
    "cloudflareinsights.com",
    "static.cloudflareinsights.com",
)


def _is_csp_violation(text: str) -> bool:
    t = text.lower()
    return "content security policy" in t or "content-security-policy" in t


def _is_benign(text: str) -> bool:
    return any(n in text for n in _BENIGN_BROWSER_NOISE)


@pytest.fixture
async def context(
    browser: Browser, request: pytest.FixtureRequest
) -> AsyncGenerator[BrowserContext, None]:
    """Create browser context with global correctness-invariant capture."""
    context = await browser.new_context(
        ignore_https_errors=True,  # Allow self-signed certs
        viewport={"width": 1280, "height": 720},
        base_url=TestConfig.APP_URL,
    )

    csp_violations: list[str] = []
    page_errors: list[str] = []
    diagnostic_errors: list[str] = []
    rate_limit_hits: list[RateLimitHit] = []
    setattr(request.node, "_e2e_rate_limit_hits", rate_limit_hits)
    setattr(request.node, "_e2e_diagnostic_errors", diagnostic_errors)
    setattr(request.node, "_e2e_pages", [])

    def _on_console(msg) -> None:
        msg_type = getattr(msg, "type", None)
        if callable(msg_type):
            msg_type = msg_type()
        if msg_type == "error":
            text = getattr(msg, "text", "")
            if callable(text):
                text = text()
            text_str = str(text)
            if not _is_benign(text_str):
                entry = f"console.error: {text_str}"
                if entry not in diagnostic_errors:
                    diagnostic_errors.append(entry)
                if _is_csp_violation(text_str):
                    csp_violations.append(text_str)

    def _on_weberror(err) -> None:
        text = str(getattr(err, "error", err))
        if not _is_benign(text):
            page_errors.append(text)
            entry = f"pageerror: {text}"
            if entry not in diagnostic_errors:
                diagnostic_errors.append(entry)

    def _on_response(response) -> None:
        record_rate_limit_response(response, rate_limit_hits)

    context.on("console", _on_console)
    context.on("weberror", _on_weberror)
    context.on("response", _on_response)

    orig_new_page = getattr(context, "new_page", None)
    if callable(orig_new_page):

        async def _wrapped_new_page(*args, **kwargs):
            new_page_obj = await orig_new_page(*args, **kwargs)
            _attach_page_diagnostics(request.node, new_page_obj)
            return new_page_obj

        try:
            setattr(context, "new_page", _wrapped_new_page)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Could not wrap context.new_page: {exc}")

    orig_context_close = getattr(context, "close", None)
    if callable(orig_context_close) and not getattr(
        context, "_e2e_close_wrapped", False
    ):

        async def _wrapped_context_close(*args, **kwargs):
            if sys.exc_info()[0] is not None or getattr(
                request.node, "_e2e_test_failed", False
            ):
                await _capture_page_failure_diagnostics(request.node)
            return await orig_context_close(*args, **kwargs)

        try:
            setattr(context, "close", _wrapped_context_close)
            setattr(context, "_e2e_close_wrapped", True)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Could not wrap context.close: {exc}")

    yield context

    invariant_failed = request.node.get_closest_marker(
        "allow_browser_errors"
    ) is None and bool(csp_violations or page_errors)
    if (
        invariant_failed
        or sys.exc_info()[0] is not None
        or getattr(request.node, "_e2e_test_failed", False)
    ):
        await _capture_page_failure_diagnostics(request.node)

    await context.close()

    if request.node.get_closest_marker("allow_browser_errors"):
        return
    assert not csp_violations, (
        "CSP violation(s) during this test — a script the app loads is blocked by "
        "its own Content-Security-Policy:\n  " + "\n  ".join(csp_violations[:5])
    )
    assert not page_errors, "Uncaught JS error(s) on a visited page:\n  " + "\n  ".join(
        page_errors[:5]
    )


@pytest.fixture
async def page(
    context: BrowserContext, request: pytest.FixtureRequest
) -> AsyncGenerator[Page, None]:
    """Create browser page."""
    page = await context.new_page()
    _attach_page_diagnostics(request.node, page)
    page.set_default_timeout(TestConfig.TIMEOUT_MS)
    try:
        yield page
    finally:
        if sys.exc_info()[0] is not None or getattr(
            request.node, "_e2e_test_failed", False
        ):
            await _capture_page_failure_diagnostics(request.node, page)
        await page.close()


@pytest.fixture
async def authenticated_page(
    context: BrowserContext,
    shared_auth_state: AuthState,
    request: pytest.FixtureRequest,
) -> AsyncGenerator[Page, None]:
    """Create browser page with authenticated user (using shared session auth).

    This fixture:
    1. Creates a new page
    2. Injects non-secret user metadata into localStorage
    3. Adds the HttpOnly auth cookie to the browser context
    4. Navigates to dashboard to verify auth works

    PERFORMANCE: 10x faster than per-test registration because auth happens
    once per session via shared_auth_state fixture.

    Use this for tests that require authentication (e.g., /statements, /accounts).
    """
    page = await context.new_page()
    _attach_page_diagnostics(request.node, page)
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

    await context.add_cookies([auth_cookie(str(shared_auth_state.access_token))])
    await context.add_init_script(
        f"""
        localStorage.setItem('finance_user_id', {json.dumps(str(shared_auth_state.user_id))});
        localStorage.setItem('finance_user_email', {json.dumps(shared_auth_state.email)});
    """
    )

    logger.info("Auth cookie and user metadata injected")

    await page.goto(f"{TestConfig.APP_URL}/dashboard", wait_until="domcontentloaded")
    await page.wait_for_load_state("domcontentloaded")
    if "/login" in page.url:
        pytest.fail(
            f"authenticated_page fixture failed: redirected to login. "
            f"Current URL: {page.url}. "
            f"Check if auth cookie and user metadata are being properly injected."
        )

    logger.info("Authentication verified successfully")

    try:
        yield page
    finally:
        if sys.exc_info()[0] is not None or getattr(
            request.node, "_e2e_test_failed", False
        ):
            await _capture_page_failure_diagnostics(request.node, page)
        await page.close()


@pytest.fixture
async def authenticated_page_unique(
    context: BrowserContext,
    request: pytest.FixtureRequest,
) -> AsyncGenerator[Page, None]:
    """Create browser page with UNIQUE test user (for isolation-critical tests).

    WARNING: This is SLOW (creates new user per test). Only use when you need
    complete isolation (e.g., testing user deletion, user-specific data).

    For most tests, use authenticated_page instead (10x faster).

    The product default accepts the AI suggestions by itself (#2405). The deterministic fixture journeys
    grade the manual review path: a person decides each row from the independent fixture, and the exact
    totals follow from those decisions. The model would post the rows before the journey reviews them. So
    the new user starts on the review path. A test of the product default carries the marker
    ``product_defaults``.
    """
    import httpx

    page = await context.new_page()
    _attach_page_diagnostics(request.node, page)
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
                    f"Registration response missing id or access_token. Got keys: {list(data.keys())}"
                )

            logger.info(f"User registered successfully: {user_id}")

            if request.node.get_closest_marker("product_defaults") is None:
                review_path = await client.patch(
                    f"{api_url}/api/users/me/settings",
                    json={"auto_accept_ai_suggestions": False},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if review_path.status_code != 200:
                    pytest.fail(
                        f"Failed to put the test user on the review path: {review_path.status_code} - {review_path.text}"
                    )

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

    # Inject auth cookie and non-secret user metadata before navigating
    # SECURITY: Use json.dumps() to prevent JavaScript injection
    await context.add_cookies([auth_cookie(str(access_token))])
    await context.add_init_script(
        f"""
        localStorage.setItem('finance_user_id', {json.dumps(str(user_id))});
        localStorage.setItem('finance_user_email', {json.dumps(test_email)});
    """
    )

    logger.info("Auth cookie and user metadata injected")

    # Navigate to a protected page to verify auth works
    await page.goto(f"{TestConfig.APP_URL}/dashboard", wait_until="domcontentloaded")

    # Verify we're NOT redirected to login
    await page.wait_for_load_state("domcontentloaded")
    if "/login" in page.url:
        pytest.fail(
            f"authenticated_page fixture failed: redirected to login. "
            f"Current URL: {page.url}. Check if auth cookie and user metadata are being properly injected."
        )

    logger.info("Authentication verified successfully")

    try:
        yield page
    finally:
        if sys.exc_info()[0] is not None or getattr(
            request.node, "_e2e_test_failed", False
        ):
            await _capture_page_failure_diagnostics(request.node, page)
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
                            f"Failed to cleanup test user {user_id}: status {delete_response.status_code}"
                        )
            except Exception as e:
                logger.debug(f"User cleanup error (non-critical): {e}")
