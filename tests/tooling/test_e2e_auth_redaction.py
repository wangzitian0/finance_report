"""Playwright E2E error output redaction for authentication headers and cookies (#2662)."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from types import ModuleType

import pytest

from tests.e2e.auth_cookie import redact_playwright_auth_headers

SAMPLE_JWT = ".".join(["eyJhbGciOiJIUzI1NiJ9", "secret", "sig"])

SAMPLE_PLAYWRIGHT_CALL_LOG = f"""playwright._impl._errors.Error: APIRequestContext.get: write EPIPE
Call log:
  - → GET https://report-staging.zitian.party/api/statements
    - user-agent: Playwright/1.50.0 (x64; ubuntu 24.04)
    - accept: */*
    - accept-encoding: gzip,deflate,br
    - Authorization: Bearer {SAMPLE_JWT}
    - cookie: finance_access_token={SAMPLE_JWT}; other_cookie=visible
    - set-cookie: finance_access_token={SAMPLE_JWT}; Path=/; HttpOnly; SameSite=Lax
"""


@dataclass
class _ReprFileLocation:
    message: str


@dataclass
class _ReprEntry:
    lines: list[str] = field(default_factory=list)


@dataclass
class _ReprTraceback:
    reprentries: list[_ReprEntry] = field(default_factory=list)


@dataclass
class _StructuredLongrepr:
    reprcrash: _ReprFileLocation
    reprtraceback: _ReprTraceback

    def __str__(self) -> str:
        entry_text = "\n".join(
            line for entry in self.reprtraceback.reprentries for line in entry.lines
        )
        return f"{entry_text}\n{self.reprcrash.message}"


@dataclass
class _Report:
    outcome: str = "failed"
    longrepr: object | None = None
    when: str = "call"
    skipped: bool = False

    @property
    def longreprtext(self) -> str:
        return str(self.longrepr or "")


@dataclass
class _Outcome:
    report: _Report

    def get_result(self) -> _Report:
        return self.report


class _Item:
    nodeid = "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py::test_hard_gate"

    def get_closest_marker(self, _name: str) -> None:
        return None


def _load_e2e_conftest_without_optional_playwright(monkeypatch):
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


def test_redact_playwright_auth_headers_scrubs_cookie_set_cookie_and_authorization() -> (
    None
):
    scrubbed = redact_playwright_auth_headers(SAMPLE_PLAYWRIGHT_CALL_LOG)

    assert SAMPLE_JWT not in scrubbed
    assert "secret_signature_value" not in scrubbed
    assert "Authorization: [REDACTED]" in scrubbed
    assert "cookie: [REDACTED]" in scrubbed
    assert "set-cookie: [REDACTED]" in scrubbed
    assert "APIRequestContext.get: write EPIPE" in scrubbed
    assert "GET https://report-staging.zitian.party/api/statements" in scrubbed


def test_redact_playwright_auth_headers_scrubs_standalone_access_token_cookie() -> None:
    raw = f"Request failed with Cookiejar entry finance_access_token={SAMPLE_JWT}; status=500"
    scrubbed = redact_playwright_auth_headers(raw)

    assert SAMPLE_JWT not in scrubbed
    assert "finance_access_token=[REDACTED]" in scrubbed


def test_makereport_scrubs_string_and_structured_longrepr(monkeypatch) -> None:
    pytest_runtest_makereport = _load_e2e_conftest_without_optional_playwright(
        monkeypatch
    ).pytest_runtest_makereport

    # 1. String longrepr
    str_report = _Report(longrepr=SAMPLE_PLAYWRIGHT_CALL_LOG)
    hook = pytest_runtest_makereport(_Item(), None)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(_Outcome(str_report))

    assert SAMPLE_JWT not in str_report.longreprtext
    assert "cookie: [REDACTED]" in str_report.longreprtext
    assert "Authorization: [REDACTED]" in str_report.longreprtext

    # 2. Structured pytest ExceptionChainRepr-like longrepr
    structured_repr = _StructuredLongrepr(
        reprcrash=_ReprFileLocation(
            message=f"Error: cookie: finance_access_token={SAMPLE_JWT}"
        ),
        reprtraceback=_ReprTraceback(
            reprentries=[
                _ReprEntry(lines=SAMPLE_PLAYWRIGHT_CALL_LOG.splitlines()),
            ]
        ),
    )
    structured_report = _Report(longrepr=structured_repr)
    hook2 = pytest_runtest_makereport(_Item(), None)
    next(hook2)
    with pytest.raises(StopIteration):
        hook2.send(_Outcome(structured_report))

    assert SAMPLE_JWT not in structured_report.longreprtext
    assert "secret_signature_value" not in structured_report.longreprtext
    assert "cookie: [REDACTED]" in structured_report.longreprtext
    assert "Authorization: [REDACTED]" in structured_report.longreprtext
