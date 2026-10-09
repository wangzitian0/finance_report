"""AC-testing.benchmarks.3: Pillars 2 and 3 browser oracle and the Playwright bridge, run against a fake Playwright (#2318).

The fake replaces `playwright` in `sys.modules`, so these tests run in CI without a browser.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

import tests.e2e as e2e_package
from tests.e2e import auth_cookie
from tests.e2e.auth_cookie import build_auth_cookie, build_runner_browser_session
from tools._lib.benchmarks.oracles import verify_browser_ui_hygiene

BASE_URL = "http://app.test"
AUTH = {
    "user_email": "qa@test.example.com",
    "user_data": {"access_token": "tok", "id": "42"},
}
ROUTES = ["/dashboard", "/reports"]


class World:
    """Scripted behavior per route path, plus a record of what the oracle did."""

    def __init__(
        self, routes: dict | None = None, launch_error: Exception | None = None
    ):
        self.routes = routes or {}
        self.launch_error = launch_error
        self.contexts: list[FakeContext] = []
        self.browsers: list[FakeBrowser] = []


class FakePage:
    def __init__(self, world: World) -> None:
        self.world = world
        self.url = "about:blank"
        self.handlers: dict = {}
        self.body = ""

    def on(self, event: str, handler) -> None:  # noqa: ANN001
        self.handlers[event] = handler

    def goto(self, url: str, timeout=None, wait_until=None):  # noqa: ANN001
        path = urlparse(url).path
        behavior = self.world.routes.get(path, {})
        if "raises" in behavior:
            raise behavior["raises"]
        self.url = BASE_URL + behavior.get("final_path", path)
        self.body = behavior.get("body", "Dashboard overview")
        for text in behavior.get("console_errors", []):
            self.handlers["console"](SimpleNamespace(type="error", text=text))
        for text in behavior.get("page_errors", []):
            self.handlers["pageerror"](text)
        return SimpleNamespace(status=behavior.get("status", 200))

    def wait_for_load_state(self, state, timeout=None) -> None:  # noqa: ANN001
        return None

    def wait_for_timeout(self, ms) -> None:  # noqa: ANN001
        return None

    def inner_text(self, selector: str) -> str:
        return self.body


class FakeContext:
    def __init__(self, world: World) -> None:
        self.world = world
        self.cookies: list = []
        self.init_scripts: list[str] = []

    def add_cookies(self, cookies: list) -> None:
        self.cookies.extend(cookies)

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def new_page(self) -> FakePage:
        return FakePage(self.world)


class FakeBrowser:
    def __init__(self, world: World) -> None:
        self.world = world
        self.closed = False

    def new_context(self, viewport=None) -> FakeContext:  # noqa: ANN001
        context = FakeContext(self.world)
        self.world.contexts.append(context)
        return context

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self, world: World) -> None:
        self.world = world
        self.chromium = SimpleNamespace(launch=self._launch)

    def _launch(self, headless: bool = True) -> FakeBrowser:
        if self.world.launch_error is not None:
            raise self.world.launch_error
        browser = FakeBrowser(self.world)
        self.world.browsers.append(browser)
        return browser


class FakePlaywrightManager:
    def __init__(self, world: World) -> None:
        self.world = world

    def __enter__(self) -> FakePlaywright:
        return FakePlaywright(self.world)

    def __exit__(self, *exc: object) -> bool:
        return False


def install_fake_playwright(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: FakePlaywrightManager(world)  # type: ignore[attr-defined]
    package = types.ModuleType("playwright")
    package.sync_api = sync_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def runner() -> SimpleNamespace:
    return SimpleNamespace(base_url=BASE_URL, last_auth_context=AUTH)


def test_clean_run_injects_the_session_and_visits_every_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    install_fake_playwright(monkeypatch, world)

    result = verify_browser_ui_hygiene(runner(), routes=ROUTES)

    assert result["status"] == "PASS"
    assert result["visited_routes"] == ROUTES
    assert result["route_errors"] == []
    context = world.contexts[0]
    assert context.cookies == [build_auth_cookie(BASE_URL, "tok")]
    assert context.init_scripts == [build_runner_browser_session(AUTH, BASE_URL)[1]]
    assert world.browsers[0].closed is True


def test_an_explicit_auth_context_wins_over_the_runner_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    install_fake_playwright(monkeypatch, world)
    other = {
        "user_email": "other@test.example.com",
        "user_data": {"access_token": "other-token", "id": "7"},
    }

    verify_browser_ui_hygiene(runner(), auth_context=other, routes=ROUTES)

    assert world.contexts[0].cookies[0]["value"] == "other-token"


def test_every_route_failing_to_load_fails_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World({r: {"raises": TimeoutError("no answer")} for r in ROUTES})
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(AssertionError, match="2 of 2 routes were not verified"):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)
    assert world.browsers[0].closed is True


def test_one_route_failing_to_load_fails_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World({"/reports": {"raises": TimeoutError("no answer")}})
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(
        AssertionError, match=r"1 of 2 routes.*\[/reports\] navigation failed"
    ):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_an_http_error_page_fails_the_check(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    world = World({"/reports": {"status": status}})
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(AssertionError, match=rf"\[/reports\] HTTP {status}"):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)


@pytest.mark.parametrize("status", [200, 204, 304])
def test_a_non_error_status_is_accepted(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    install_fake_playwright(monkeypatch, World({"/reports": {"status": status}}))

    assert verify_browser_ui_hygiene(runner(), routes=ROUTES)["status"] == "PASS"


@pytest.mark.parametrize("final_path", ["/login", "/login/", "/login/expired"])
def test_a_redirect_to_login_fails_the_check(
    monkeypatch: pytest.MonkeyPatch, final_path: str
) -> None:
    world = World({"/dashboard": {"final_path": final_path}})
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(AssertionError, match=r"\[/dashboard\] redirected to /login"):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)


def test_the_login_route_itself_may_end_on_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_playwright(monkeypatch, World())

    result = verify_browser_ui_hygiene(runner(), routes=["/login"])

    assert result["visited_routes"] == ["/login"]


def test_a_console_error_fails_pillar_2(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World({"/dashboard": {"console_errors": ["CSP violation"]}})
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(AssertionError, match="Pillar 2 .*CSP violation"):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)


def test_an_uncaught_page_error_fails_pillar_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World({"/dashboard": {"page_errors": ["TypeError: x is undefined"]}})
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(AssertionError, match="Pillar 2 .*TypeError"):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)


def test_a_favicon_console_error_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World({"/dashboard": {"console_errors": ["GET /favicon.ico 404"]}})
    install_fake_playwright(monkeypatch, world)

    assert verify_browser_ui_hygiene(runner(), routes=ROUTES)["status"] == "PASS"


def test_developer_jargon_in_the_page_fails_pillar_3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World({"/reports": {"body": "Report none generated"}})
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(AssertionError, match=r"Pillar 3 .*\[/reports\]"):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)


def test_an_empty_route_list_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_playwright(monkeypatch, World())

    with pytest.raises(ValueError, match="at least one route"):
        verify_browser_ui_hygiene(runner(), routes=[])


def test_missing_playwright_is_skipped_or_raised_by_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)

    skipped = verify_browser_ui_hygiene(runner(), routes=ROUTES)
    assert skipped["status"] == "SKIPPED"
    assert skipped["reason"] == "playwright_not_installed"
    with pytest.raises(ImportError):
        verify_browser_ui_hygiene(
            runner(), routes=ROUTES, allow_skip_if_no_browser=False
        )


def test_a_browser_launch_failure_is_skipped_or_raised_by_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_playwright(
        monkeypatch, World(launch_error=RuntimeError("no chromium"))
    )

    skipped = verify_browser_ui_hygiene(runner(), routes=ROUTES)
    assert skipped["status"] == "SKIPPED"
    assert "no chromium" in skipped["reason"]
    with pytest.raises(RuntimeError, match="no chromium"):
        verify_browser_ui_hygiene(
            runner(), routes=ROUTES, allow_skip_if_no_browser=False
        )


def test_a_bad_auth_context_fails_before_any_browser_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    install_fake_playwright(monkeypatch, world)

    with pytest.raises(ValueError, match="Invalid auth context"):
        verify_browser_ui_hygiene(
            runner(),
            auth_context={"user_data": {}, "user_email": "q@t.example"},
            routes=ROUTES,
        )
    assert world.browsers == []


def test_the_oracle_uses_the_shared_session_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_playwright(monkeypatch, World())

    def sentinel(auth_context: dict, app_url: str) -> None:
        raise RuntimeError("shared-builder-called")

    monkeypatch.setattr(auth_cookie, "build_runner_browser_session", sentinel)
    with pytest.raises(RuntimeError, match="shared-builder-called"):
        verify_browser_ui_hygiene(runner(), routes=ROUTES)


# ------------------------------------------------------------------- bridge


class FakeAsyncContext:
    def __init__(self) -> None:
        self.cookies: list = []
        self.init_scripts: list[str] = []

    async def add_cookies(self, cookies: list) -> None:
        self.cookies.extend(cookies)

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


@pytest.fixture
def builder_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[dict, str]]:
    """Wrap the shared builder so a test can see who calls it."""
    calls: list[tuple[dict, str]] = []
    real = auth_cookie.build_runner_browser_session

    def recording(auth_context: dict, app_url: str):
        calls.append((auth_context, app_url))
        return real(auth_context, app_url)

    monkeypatch.setattr(auth_cookie, "build_runner_browser_session", recording)
    return calls


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch, builder_calls: list):
    """Import `tests.e2e.bench_ui_bridge` against a stub `playwright.async_api`, then remove it."""
    async_api = types.ModuleType("playwright.async_api")
    async_api.Page = object  # type: ignore[attr-defined]
    package = types.ModuleType("playwright")
    package.async_api = async_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    sys.modules.pop("tests.e2e.bench_ui_bridge", None)
    module = importlib.import_module("tests.e2e.bench_ui_bridge")
    yield module
    sys.modules.pop("tests.e2e.bench_ui_bridge", None)
    if hasattr(e2e_package, "bench_ui_bridge"):
        delattr(e2e_package, "bench_ui_bridge")


def test_the_bridge_injects_the_cookie_and_script_from_the_shared_builder(
    bridge, builder_calls: list
) -> None:
    context = FakeAsyncContext()
    page = SimpleNamespace(context=context)

    asyncio.run(
        bridge.BenchUiBridge.inject_runner_session_to_browser(page, AUTH, BASE_URL)
    )

    cookie, script = build_runner_browser_session(AUTH, BASE_URL)
    assert context.cookies == [cookie]
    assert context.init_scripts == [script]
    assert builder_calls[0] == (AUTH, BASE_URL)


def test_the_bridge_injects_nothing_for_a_bad_auth_context(bridge) -> None:
    context = FakeAsyncContext()
    page = SimpleNamespace(context=context)

    with pytest.raises(ValueError, match="Invalid auth context"):
        asyncio.run(
            bridge.BenchUiBridge.inject_runner_session_to_browser(
                page, {"user_data": {}, "user_email": "q@t.example"}, BASE_URL
            )
        )
    assert context.cookies == []
    assert context.init_scripts == []
