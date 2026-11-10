'AC-testing.e2e-auth-redaction.1'; from __future__ import annotations; import importlib; import sys; from dataclasses import dataclass, field; from types import ModuleType; import pytest; from tests.e2e.auth_cookie import redact_playwright_auth_headers; SAMPLE_JWT = '.'.join(['eyJhbGciOiJIUzI1NiJ9', 'secret', 'sig']); SAMPLE_PLAYWRIGHT_CALL_LOG = f'playwright._impl._errors.Error: APIRequestContext.get: write EPIPE\nCall log:\n  - → GET https://report-staging.zitian.party/api/statements\n    - user-agent: Playwright/1.50.0 (x64; ubuntu 24.04)\n    - accept: */*\n    - accept-encoding: gzip,deflate,br\n    - Authorization: Bearer {SAMPLE_JWT}\n    - cookie: finance_access_token={SAMPLE_JWT}; other_cookie=visible\n    - set-cookie: finance_access_token={SAMPLE_JWT}; Path=/; HttpOnly; SameSite=Lax\n'
@dataclass
class _ReprFileLocation: message: str
@dataclass
class _ReprEntry: lines: list[str] = field(default_factory=list)
@dataclass
class _ReprTraceback: reprentries: list[_ReprEntry] = field(default_factory=list)
@dataclass
class _StructuredLongrepr:
    reprcrash: _ReprFileLocation; reprtraceback: _ReprTraceback
    def __str__(self) -> str: entry_text = '\n'.join((line for entry in self.reprtraceback.reprentries for line in entry.lines)); return f'{entry_text}\n{self.reprcrash.message}'
@dataclass
class _Report:
    outcome: str = 'failed'; longrepr: object | None = None; when: str = 'call'; skipped: bool = False
    @property
    def longreprtext(self) -> str: return str(self.longrepr or '')
@dataclass
class _Outcome:
    report: _Report
    def get_result(self) -> _Report: return self.report
class _Item:
    nodeid = 'tests/e2e/test_vision_upload_to_dashboard_hard_gate.py::test_hard_gate'
    def get_closest_marker(self, _name: str) -> None: return None
def _load_e2e_conftest_without_optional_playwright(monkeypatch): playwright_module = ModuleType('playwright'); async_api_module = ModuleType('playwright.async_api'); [setattr(async_api_module, name, type(name, (), {})) for name in ('Browser', 'BrowserContext', 'Page')]; setattr(async_api_module, 'async_playwright', lambda: None); setattr(playwright_module, 'async_api', async_api_module); monkeypatch.setitem(sys.modules, 'playwright', playwright_module); monkeypatch.setitem(sys.modules, 'playwright.async_api', async_api_module); sys.modules.pop('tests.e2e.conftest', None); return importlib.import_module('tests.e2e.conftest')
def test_redact_playwright_auth_headers_scrubs_cookie_set_cookie_and_authorization() -> None: scrubbed = redact_playwright_auth_headers(SAMPLE_PLAYWRIGHT_CALL_LOG); assert SAMPLE_JWT not in scrubbed; assert 'secret_signature_value' not in scrubbed; assert 'Authorization: [REDACTED]' in scrubbed; assert 'cookie: [REDACTED]' in scrubbed; assert 'set-cookie: [REDACTED]' in scrubbed; assert 'APIRequestContext.get: write EPIPE' in scrubbed; assert 'GET https://report-staging.zitian.party/api/statements' in scrubbed; _m1_raw = f'Request failed with Cookiejar entry finance_access_token={SAMPLE_JWT}; status=500'; _m1_scrubbed = redact_playwright_auth_headers(_m1_raw); assert SAMPLE_JWT not in _m1_scrubbed; assert 'finance_access_token=[REDACTED]' in _m1_scrubbed
def test_AC_testing_e2e_auth_redaction_1_makereport_scrubs_string_and_structured_longrepr(monkeypatch) -> None:
    pytest_runtest_makereport = _load_e2e_conftest_without_optional_playwright(monkeypatch).pytest_runtest_makereport; str_report = _Report(longrepr=SAMPLE_PLAYWRIGHT_CALL_LOG); hook = pytest_runtest_makereport(_Item(), None); next(hook)
    with pytest.raises(StopIteration): hook.send(_Outcome(str_report))
    assert SAMPLE_JWT not in str_report.longreprtext; assert 'cookie: [REDACTED]' in str_report.longreprtext; assert 'Authorization: [REDACTED]' in str_report.longreprtext; structured_repr = _StructuredLongrepr(reprcrash=_ReprFileLocation(message=f'Error: cookie: finance_access_token={SAMPLE_JWT}'), reprtraceback=_ReprTraceback(reprentries=[_ReprEntry(lines=SAMPLE_PLAYWRIGHT_CALL_LOG.splitlines())])); structured_report = _Report(longrepr=structured_repr); hook2 = pytest_runtest_makereport(_Item(), None); next(hook2)
    with pytest.raises(StopIteration): hook2.send(_Outcome(structured_report))
    assert SAMPLE_JWT not in structured_report.longreprtext; assert 'secret_signature_value' not in structured_report.longreprtext; assert 'cookie: [REDACTED]' in structured_report.longreprtext; assert 'Authorization: [REDACTED]' in structured_report.longreprtext
