"""AC-testing.e2e-failure-diagnostics.1 / AC-testing.e2e-failure-diagnostics.2: E2E failure diagnostics and touched journey selector (#2745, #2670)."""

from __future__ import annotations

import asyncio
import importlib
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from common.testing import matrix, test_selection

SAMPLE_JWT = ".".join(["eyJhbGciOiJIUzI1NiJ9", "secret_payload", "sig_value"])
PNG_MAGIC = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


class _FakeConsoleMessage:
    def __init__(self, msg_type: str, text: str) -> None:
        self.type = msg_type
        self.text = text


class _FakeLocator:
    def __init__(self, body_text: str, *, fail_inner_text: bool = False) -> None:
        self._body_text = body_text
        self._fail_inner_text = fail_inner_text

    async def inner_text(self, timeout: int = 2000) -> str:
        assert timeout == 2000
        if self._fail_inner_text:
            raise RuntimeError("locator timed out")
        return self._body_text


class _FakePage:
    def __init__(
        self,
        body_text: str = "Reconciliation Workbench\n4 records",
        *,
        fail_inner_text: bool = False,
    ) -> None:
        self.body_text = body_text
        self.fail_inner_text = fail_inner_text
        self.handlers: dict[str, list] = {}
        self.closed = False
        self.screenshot_calls: list[tuple[str, bool]] = []
        self.timeout_ms: int | None = None

    def on(self, event: str, handler) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, payload: object) -> None:
        for handler in self.handlers.get(event, []):
            handler(payload)

    def set_default_timeout(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms

    def is_closed(self) -> bool:
        return self.closed

    def locator(self, selector: str) -> _FakeLocator:
        assert selector == "body"
        return _FakeLocator(self.body_text, fail_inner_text=self.fail_inner_text)

    async def evaluate(self, _expression: str) -> str:
        return self.body_text

    async def screenshot(self, *, path: str, full_page: bool = False) -> bytes:
        assert not self.closed, "screenshot must be captured before page.close()"
        self.screenshot_calls.append((path, full_page))
        Path(path).write_bytes(PNG_MAGIC)
        return PNG_MAGIC

    async def close(self) -> None:
        self.closed = True


class _FakeBrowserContext:
    def __init__(self, page: _FakePage | None = None) -> None:
        self._page = page or _FakePage()
        self.handlers: dict[str, list] = {}
        self.closed = False

    def on(self, event: str, handler) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, payload: object) -> None:
        for handler in self.handlers.get(event, []):
            handler(payload)

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeBrowserContext) -> None:
        self._context = context

    async def new_context(self, **_kwargs) -> _FakeBrowserContext:
        return self._context


class _Item:
    def __init__(
        self,
        nodeid: str = "tests/e2e/test_reconciliation_ui_journey.py::test_reconciliation_unmatched_interactive_disposition",
    ) -> None:
        self.nodeid = nodeid

    def get_closest_marker(self, _name: str) -> None:
        return None


@dataclass
class _FixtureRequest:
    node: _Item


@dataclass
class _Report:
    outcome: str = "failed"
    longrepr: object | None = "AssertionError: Locator expected to be visible"
    when: str = "call"
    skipped: bool = False

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"


@dataclass
class _Outcome:
    report: _Report

    def get_result(self) -> _Report:
        return self.report


def _load_e2e_conftest_without_optional_playwright(monkeypatch: pytest.MonkeyPatch):
    playwright_module = ModuleType("playwright")
    async_api_module = ModuleType("playwright.async_api")
    for name in ("Browser", "BrowserContext", "Page"):
        setattr(async_api_module, name, type(name, (), {}))
    setattr(async_api_module, "async_playwright", lambda: None)
    setattr(playwright_module, "async_api", async_api_module)
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)
    sys.modules.pop("tests.e2e.conftest", None)
    return importlib.import_module("tests.e2e.conftest")


def test_AC_testing_e2e_failure_diagnostics_1_failed_page_test_writes_screenshot_bounded_redacted_text_and_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test 1 (#2745): A failing test with a page produces screenshot.png, page-text.txt (<=4096 bytes, redacted), and page-errors.txt (redacted)."""
    monkeypatch.setenv("E2E_FAILURE_ARTIFACT_DIR", str(tmp_path))
    conftest = _load_e2e_conftest_without_optional_playwright(monkeypatch)

    long_body = (
        f"Unmatched Transactions: 4 records\n"
        f"Authorization: Bearer {SAMPLE_JWT}\n"
        f"cookie: finance_access_token={SAMPLE_JWT}\n"
        + ("Visible row details ABCDEFG\n" * 300)
    )
    fake_page = _FakePage(body_text=long_body)
    fake_ctx = _FakeBrowserContext(page=fake_page)
    fake_browser = _FakeBrowser(context=fake_ctx)
    item = _Item()
    request = _FixtureRequest(node=item)

    async def exercise_failing_journey() -> None:
        ctx_gen = conftest.context.__wrapped__(fake_browser, request)
        ctx = await ctx_gen.__anext__()
        page_gen = conftest.page.__wrapped__(ctx, request)
        page = await page_gen.__anext__()

        # Emit both console.error and pageerror containing secrets
        page.emit(
            "console",
            _FakeConsoleMessage(
                "error",
                f"POST /reconciliation/unmatched failed with Authorization: Bearer {SAMPLE_JWT}",
            ),
        )
        page.emit(
            "pageerror",
            RuntimeError(f"Uncaught TypeError with finance_access_token={SAMPLE_JWT}"),
        )

        # Simulate test call failure before fixture teardown closes page/context
        try:
            raise AssertionError("Locator expected '3 records' to be visible")
        except AssertionError:
            with pytest.raises(StopAsyncIteration):
                await page_gen.asend(None)

        assert fake_page.closed is True

    asyncio.run(exercise_failing_journey())

    expected_dir = tmp_path / conftest._sanitize_nodeid(item.nodeid)
    assert expected_dir.is_dir()

    screenshot_file = expected_dir / "screenshot.png"
    page_text_file = expected_dir / "page-text.txt"
    page_errors_file = expected_dir / "page-errors.txt"

    assert screenshot_file.is_file()
    screenshot_bytes = screenshot_file.read_bytes()
    assert len(screenshot_bytes) > 0
    assert screenshot_bytes.startswith(b"\x89PNG")
    assert fake_page.screenshot_calls == [(str(screenshot_file), True)]

    assert page_text_file.is_file()
    page_text_bytes = page_text_file.read_bytes()
    assert 0 < len(page_text_bytes) <= conftest.PAGE_TEXT_MAX_BYTES
    assert len(page_text_bytes) == 4096
    page_text = page_text_bytes.decode("utf-8")
    assert SAMPLE_JWT not in page_text
    assert "Authorization: [REDACTED]" in page_text
    assert "cookie: [REDACTED]" in page_text

    assert page_errors_file.is_file()
    page_errors = page_errors_file.read_text(encoding="utf-8")
    assert SAMPLE_JWT not in page_errors
    assert "console.error:" in page_errors
    assert "Authorization: [REDACTED]" in page_errors
    assert "pageerror:" in page_errors
    assert "finance_access_token=[REDACTED]" in page_errors


def test_failing_page_test_with_zero_console_errors_still_writes_deterministic_three_files_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify fallback innerText, empty page-errors.txt creation, and deduplication across makereport + teardown (#2745)."""
    monkeypatch.setenv("E2E_FAILURE_ARTIFACT_DIR", str(tmp_path))
    conftest = _load_e2e_conftest_without_optional_playwright(monkeypatch)

    fake_page = _FakePage(
        body_text="Fallback document.body.innerText content",
        fail_inner_text=True,
    )
    fake_ctx = _FakeBrowserContext(page=fake_page)
    fake_browser = _FakeBrowser(context=fake_ctx)
    item = _Item("tests/e2e/test_journal_ui_journey.py::test_journal_modal")
    request = _FixtureRequest(node=item)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        ctx_gen = conftest.context.__wrapped__(fake_browser, request)
        ctx = loop.run_until_complete(ctx_gen.__anext__())
        page_gen = conftest.page.__wrapped__(ctx, request)
        loop.run_until_complete(page_gen.__anext__())

        # Trigger pytest_runtest_makereport while page is still open
        hook = conftest.pytest_runtest_makereport(item, None)
        next(hook)
        with pytest.raises(StopIteration):
            hook.send(_Outcome(_Report(outcome="failed", when="call")))

        assert getattr(item, "_e2e_diagnostics_captured", False) is True
        assert len(fake_page.screenshot_calls) == 1

        # Teardown closes page and context; deduplication prevents a second screenshot
        with pytest.raises(StopAsyncIteration):
            loop.run_until_complete(page_gen.__anext__())
        with pytest.raises(StopAsyncIteration):
            loop.run_until_complete(ctx_gen.__anext__())
        assert len(fake_page.screenshot_calls) == 1
    finally:
        loop.close()

    expected_dir = tmp_path / conftest._sanitize_nodeid(item.nodeid)
    assert (expected_dir / "screenshot.png").is_file()
    assert (expected_dir / "page-text.txt").read_text(encoding="utf-8") == (
        "Fallback document.body.innerText content"
    )
    assert (expected_dir / "page-errors.txt").is_file()
    assert (expected_dir / "page-errors.txt").read_text(encoding="utf-8") == ""


def test_passing_page_test_produces_zero_files_in_e2e_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test 2 (#2745): A passing test with a page produces zero files in e2e-failures."""
    monkeypatch.setenv("E2E_FAILURE_ARTIFACT_DIR", str(tmp_path))
    conftest = _load_e2e_conftest_without_optional_playwright(monkeypatch)

    fake_page = _FakePage(body_text="Healthy page body")
    fake_ctx = _FakeBrowserContext(page=fake_page)
    fake_browser = _FakeBrowser(context=fake_ctx)
    item = _Item("tests/e2e/test_epic022_ia_shell.py::test_everyday_user_shell")
    request = _FixtureRequest(node=item)

    async def exercise_passing_journey() -> None:
        ctx_gen = conftest.context.__wrapped__(fake_browser, request)
        ctx = await ctx_gen.__anext__()
        page_gen = conftest.page.__wrapped__(ctx, request)
        _page = await page_gen.__anext__()

        hook = conftest.pytest_runtest_makereport(item, None)
        next(hook)
        with pytest.raises(StopIteration):
            hook.send(_Outcome(_Report(outcome="passed", longrepr=None, when="call")))

        with pytest.raises(StopAsyncIteration):
            await page_gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await ctx_gen.__anext__()

    asyncio.run(exercise_passing_journey())

    assert list(tmp_path.iterdir()) == []
    assert fake_page.screenshot_calls == []


def test_AC_testing_e2e_failure_diagnostics_2_select_touched_e2e_maps_specs_and_frontend_routes_without_llm(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 3 (#2670): select_touched_e2e and --touched-files map touched specs and frontend routes without selecting LLM journeys."""
    # 1. Direct touch on reconciliation E2E spec selects reconciliation journey
    assert matrix.select_touched_e2e(
        ["tests/e2e/test_reconciliation_ui_journey.py"]
    ) == ["tests/e2e/test_reconciliation_ui_journey.py"]

    # 2. Touching frontend reconciliation page or component selects reconciliation journey
    assert matrix.select_touched_e2e(
        ["apps/frontend/src/app/(main)/reconciliation/page.tsx"]
    ) == ["tests/e2e/test_reconciliation_ui_journey.py"]
    assert matrix.select_touched_e2e(
        ["apps/frontend/src/components/reconciliation/UnmatchedBoard.tsx"]
    ) == ["tests/e2e/test_reconciliation_ui_journey.py"]

    # 3. Touching LLM-dependent journeys never selects any LLM journey
    llm_files = [
        row.file for row in matrix.E2E_ROWS if matrix.NEEDS_LLM_PROVIDER in row.needs
    ]
    assert llm_files
    assert matrix.select_touched_e2e(llm_files) == []

    # 4. Touching unrelated backend, docs, or blank paths selects nothing
    assert (
        matrix.select_touched_e2e(
            [
                "",
                "   ",
                "apps/backend/src/ledger/service.py",
                "docs/project/README.md",
                "README.md",
            ]
        )
        == []
    )

    # 5. Touching shared E2E harness (tests/e2e/conftest.py) selects all staging_core_e2e journeys
    all_core = list(matrix.staging_core_e2e_selection())
    assert matrix.select_touched_e2e(["tests/e2e/conftest.py"]) == all_core
    for selected_file in all_core:
        row = next(r for r in matrix.E2E_ROWS if r.file == selected_file)
        assert matrix.NEEDS_LLM_PROVIDER not in row.needs

    # 6. CLI --touched-files plain and --shell output round-trips
    rc = test_selection.main(
        [
            "--touched-files",
            "apps/frontend/src/app/(main)/reconciliation/page.tsx",
            "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip().splitlines() == [
        "tests/e2e/test_reconciliation_ui_journey.py"
    ]

    rc_shell = test_selection.main(
        [
            "--touched-files",
            "tests/e2e/test_reconciliation_ui_journey.py",
            "--shell",
        ]
    )
    assert rc_shell == 0
    shell_lines = capsys.readouterr().out.strip().splitlines()
    assert shell_lines[0].startswith("TOUCHED_E2E_TESTS=(")
    parsed_tests = shlex.split(shell_lines[0][len("TOUCHED_E2E_TESTS=(") : -1])
    assert parsed_tests == ["tests/e2e/test_reconciliation_ui_journey.py"]
    assert shlex.split(shell_lines[1].split("=", 1)[1]) == [
        matrix.STAGING_CORE_E2E_MARKER
    ]
    assert shell_lines[2] == "TOUCHED_E2E_COUNT=1"
