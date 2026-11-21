# ruff: noqa: E402
import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.e2e._journey_helpers import (  # noqa: E402
    AuthState,
    capture_page_failure_diagnostics,
    delete_e2e_user,
    open_authenticated_page,
    register_e2e_user,
    scrub_report_longrepr,
    verify_session_target,
)
from tests.e2e.auth_cookie import build_auth_cookie  # noqa: E402
from tests.e2e.deployment_pin import expected_version_from_env  # noqa: E402
from tests.e2e.critical_skip_gate import (
    CRITICAL_MARKER,
    critical_skip_failure_message,
    should_convert_skip_to_failure,
)  # noqa: E402
from tests.e2e.e2e_rate_limit import (
    fail_report_for_rate_limits,
    record_rate_limit_response,
)  # noqa: E402

_BENIGN_BROWSER_NOISE = ("cloudflareinsights.com", "static.cloudflareinsights.com")


class TestConfig:
    APP_URL = (
        os.getenv("APP_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000"
    )
    TEST_ENV = os.getenv("TEST_ENV", "staging").lower()
    EXPECTED_SHA = expected_version_from_env()
    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "30000"))
    SLOW_MO = int(os.getenv("SLOW_MO", "0"))
    STORAGE_STATE_PATH = ROOT / "tests" / "e2e" / ".auth" / "state.json"


def _strict_e2e_gates_enabled() -> bool:
    return os.getenv("STRICT_E2E_GATES", "").lower() in {"1", "true", "yes"}


def is_strict_or_ci() -> bool:
    return _strict_e2e_gates_enabled() or os.getenv("CI") == "true"


def pytest_sessionstart(session) -> None:
    if is_strict_or_ci() and TestConfig.TEST_ENV != "local":
        verify_session_target(
            session, app_url=TestConfig.APP_URL, expected_sha=TestConfig.EXPECTED_SHA
        )


def format_ai_ocr_gate_failure(
    message: str, *, statement: dict | None = None, model: str | None = None
) -> str:
    details = [f"model={model}"] if model else []
    if statement:
        details.extend(
            f"{k}={v}"
            for k in (
                "id",
                "status",
                "validation_error",
                "confidence_score",
                "parsing_progress",
                "balance_validated",
            )
            if (v := statement.get(k)) not in (None, "")
        )
    return f"{message}. Details: {'; '.join(details)}" if details else message


def fail_or_skip_ai_ocr_gate(
    message: str, *, statement: dict | None = None, model: str | None = None
) -> None:
    failure_message = format_ai_ocr_gate_failure(
        message, statement=statement, model=model
    )
    if _strict_e2e_gates_enabled():
        pytest.fail(failure_message)
    pytest.skip(
        f"{failure_message} STRICT_E2E_GATES is not enabled for this environment."
    )


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
        report.outcome, report.longrepr = (
            "failed",
            critical_skip_failure_message(item.nodeid),
        )
    hits = getattr(item, "_e2e_rate_limit_hits", [])
    if (
        report.when in {"call", "teardown"}
        and hits
        and not getattr(item, "_e2e_rate_limit_reported", False)
        and fail_report_for_rate_limits(report, hits)
    ):
        setattr(item, "_e2e_rate_limit_reported", True)
    scrub_report_longrepr(report)
    if getattr(report, "failed", False) or getattr(report, "outcome", "") == "failed":
        setattr(item, "_e2e_test_failed", True)
        if not getattr(item, "_e2e_diagnostics_captured", False) and getattr(
            item, "_e2e_pages", None
        ):
            try:
                loop = asyncio.get_event_loop()
                if not loop.is_running() and not loop.is_closed():
                    loop.run_until_complete(capture_page_failure_diagnostics(item))
            except Exception:
                pass


def auth_cookie(access_token: str) -> dict[str, object]:
    try:
        return build_auth_cookie(TestConfig.APP_URL, access_token)
    except ValueError as exc:
        pytest.fail(str(exc))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def config() -> TestConfig:
    return TestConfig()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def shared_auth_state() -> AsyncGenerator[AuthState, None]:
    state = await register_e2e_user(TestConfig.APP_URL, "e2e-session")
    yield state
    await delete_e2e_user(TestConfig.APP_URL, state)


@pytest.fixture
async def browser() -> AsyncGenerator[Browser, None]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=TestConfig.HEADLESS, slow_mo=TestConfig.SLOW_MO
        )
        yield browser
        await browser.close()


@pytest.fixture
async def context(
    browser: Browser, request: pytest.FixtureRequest
) -> AsyncGenerator[BrowserContext, None]:
    context = await browser.new_context(
        ignore_https_errors=True,
        viewport={"width": 1280, "height": 720},
        base_url=TestConfig.APP_URL,
    )
    csp_violations, page_errors, diagnostic_errors, rate_limit_hits = [], [], [], []
    (
        request.node._e2e_rate_limit_hits,
        request.node._e2e_diagnostic_errors,
        request.node._e2e_pages,
    ) = rate_limit_hits, diagnostic_errors, []

    def _on_console(msg) -> None:
        if (
            msg.type()
            if callable(getattr(msg, "type", None))
            else getattr(msg, "type", None)
        ) == "error":
            text = str(
                msg.text()
                if callable(getattr(msg, "text", None))
                else getattr(msg, "text", "")
            )
            if not any(n in text for n in _BENIGN_BROWSER_NOISE):
                diagnostic_errors.append(f"console.error: {text}")
                if (
                    "content security policy" in text.lower()
                    or "content-security-policy" in text.lower()
                ):
                    csp_violations.append(text)

    def _on_weberror(err) -> None:
        text = str(getattr(err, "error", err))
        if not any(n in text for n in _BENIGN_BROWSER_NOISE):
            page_errors.append(text)
            diagnostic_errors.append(f"pageerror: {text}")

    context.on("console", _on_console)
    context.on("weberror", _on_weberror)
    context.on(
        "response", lambda resp: record_rate_limit_response(resp, rate_limit_hits)
    )
    context.on("page", lambda p: request.node._e2e_pages.append(p))
    yield context
    allow_errors = request.node.get_closest_marker("allow_browser_errors") is not None
    if (
        (not allow_errors and (csp_violations or page_errors))
        or sys.exc_info()[0] is not None
        or getattr(request.node, "_e2e_test_failed", False)
    ):
        await capture_page_failure_diagnostics(request.node)
    await context.close()
    if not allow_errors:
        assert not csp_violations, "CSP violation(s):\n  " + "\n  ".join(
            csp_violations[:5]
        )
        assert not page_errors, "Uncaught JS error(s):\n  " + "\n  ".join(
            page_errors[:5]
        )


async def _teardown_page(
    request: pytest.FixtureRequest, page: Page, state: AuthState | None = None
) -> None:
    if sys.exc_info()[0] is not None or getattr(
        request.node, "_e2e_test_failed", False
    ):
        await capture_page_failure_diagnostics(request.node, page)
    await page.close()
    if state is not None:
        await delete_e2e_user(TestConfig.APP_URL, state)


@pytest.fixture
async def page(
    context: BrowserContext, request: pytest.FixtureRequest
) -> AsyncGenerator[Page, None]:
    page = await context.new_page()
    page.set_default_timeout(TestConfig.TIMEOUT_MS)
    try:
        yield page
    finally:
        await _teardown_page(request, page)


@pytest.fixture
async def authenticated_page(
    context: BrowserContext,
    shared_auth_state: AuthState,
    request: pytest.FixtureRequest,
) -> AsyncGenerator[Page, None]:
    page = await open_authenticated_page(
        context,
        request,
        shared_auth_state,
        base_url=TestConfig.APP_URL,
        timeout_ms=TestConfig.TIMEOUT_MS,
    )
    try:
        yield page
    finally:
        await _teardown_page(request, page)


@pytest.fixture
async def authenticated_page_unique(
    context: BrowserContext, request: pytest.FixtureRequest
) -> AsyncGenerator[Page, None]:
    state = await register_e2e_user(
        TestConfig.APP_URL,
        "e2e-unique",
        disable_auto_accept=request.node.get_closest_marker("product_defaults") is None,
    )
    page = await open_authenticated_page(
        context,
        request,
        state,
        base_url=TestConfig.APP_URL,
        timeout_ms=TestConfig.TIMEOUT_MS,
    )
    try:
        yield page
    finally:
        await _teardown_page(request, page, state)
