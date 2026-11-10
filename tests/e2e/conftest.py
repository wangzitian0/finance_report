import asyncio; import json; import logging; import os; import re; import sys; import uuid; from collections.abc import AsyncGenerator; from datetime import datetime; from pathlib import Path; import pytest; from playwright.async_api import Browser, BrowserContext, Page, async_playwright; ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None; from common.testing.e2e_rate_limit import RateLimitHit, fail_report_for_rate_limits, record_rate_limit_response; from tests.e2e.auth_cookie import build_auth_cookie, redact_playwright_auth_headers; from tests.e2e.critical_skip_gate import CRITICAL_MARKER, critical_skip_failure_message, should_convert_skip_to_failure; from tests.e2e.path_quality import HANDSHAKE_USER_AGENT, report_path_quality; logger = logging.getLogger(__name__); PAGE_TEXT_MAX_BYTES = 4096; _NODEID_UNSAFE_RE = re.compile('[^A-Za-z0-9._-]+')
def _sanitize_nodeid(nodeid: str) -> str: sanitized = _NODEID_UNSAFE_RE.sub('__', nodeid.strip()).strip('._-'); return sanitized or 'unknown_test'
def _failure_artifact_dir(item: object) -> Path: root = Path(os.getenv('E2E_FAILURE_ARTIFACT_DIR') or ROOT / 'test-results' / 'e2e-failures'); nodeid = str(getattr(item, 'nodeid', 'unknown_test')); return root / _sanitize_nodeid(nodeid)
def _truncate_utf8_bytes(text: str, max_bytes: int=PAGE_TEXT_MAX_BYTES) -> str:
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes: return text
    return encoded[:max_bytes].decode('utf-8', errors='ignore')
async def _read_visible_body_text(page: object) -> str:
    locator_fn = getattr(page, 'locator', None)
    if callable(locator_fn):
        try:
            body = locator_fn('body'); inner_text_fn = getattr(body, 'inner_text', None)
            if callable(inner_text_fn):
                text = await inner_text_fn(timeout=2000)
                if isinstance(text, str): return text
        except Exception as exc: logger.debug(f'body.inner_text() fallback triggered: {exc}')
    evaluate_fn = getattr(page, 'evaluate', None)
    if callable(evaluate_fn):
        try:
            text = await evaluate_fn("() => (document && document.body && document.body.innerText) || ''")
            if isinstance(text, str): return text
        except Exception as exc: logger.debug(f'document.body.innerText fallback failed: {exc}')
    return ''
async def _capture_page_failure_diagnostics(item: object, page: object | None=None) -> Path | None:
    if getattr(item, '_e2e_diagnostics_captured', False): return getattr(item, '_e2e_diagnostics_dir', None)
    pages: list[object] = list(getattr(item, '_e2e_pages', [])); target_page = page
    if target_page is None:
        for candidate in reversed(pages):
            is_closed_fn = getattr(candidate, 'is_closed', None); closed = is_closed_fn() if callable(is_closed_fn) else False
            if not closed: target_page = candidate; break
        if target_page is None and pages: target_page = pages[-1]
    if target_page is None: return None
    setattr(item, '_e2e_diagnostics_captured', True); artifact_dir = _failure_artifact_dir(item); artifact_dir.mkdir(parents=True, exist_ok=True); setattr(item, '_e2e_diagnostics_dir', artifact_dir); screenshot_path = artifact_dir / 'screenshot.png'; page_text_path = artifact_dir / 'page-text.txt'; page_errors_path = artifact_dir / 'page-errors.txt'; screenshot_fn = getattr(target_page, 'screenshot', None)
    if callable(screenshot_fn):
        try: data = await screenshot_fn(path=str(screenshot_path), full_page=True); screenshot_path.write_bytes(bytes(data)) if not screenshot_path.exists() and isinstance(data, (bytes, bytearray)) else None
        except Exception as exc: logger.warning(f'Failed to capture E2E failure screenshot: {exc}')
    raw_body_text = await _read_visible_body_text(target_page); scrubbed_body_text = redact_playwright_auth_headers(raw_body_text); bounded_body_text = _truncate_utf8_bytes(scrubbed_body_text, PAGE_TEXT_MAX_BYTES); page_text_path.write_text(bounded_body_text, encoding='utf-8'); diagnostic_errors: list[str] = list(getattr(item, '_e2e_diagnostic_errors', [])); scrubbed_errors = redact_playwright_auth_headers('\n'.join(diagnostic_errors)); page_errors_path.write_text(scrubbed_errors, encoding='utf-8'); return artifact_dir
def _attach_page_diagnostics(item: object, page: object) -> None:
    pages: list[object] = getattr(item, '_e2e_pages', None)
    if pages is None: pages = []; setattr(item, '_e2e_pages', pages)
    pages.append(page) if page not in pages else None; diagnostic_errors: list[str] = getattr(item, '_e2e_diagnostic_errors', None)
    if diagnostic_errors is None: diagnostic_errors = []; setattr(item, '_e2e_diagnostic_errors', diagnostic_errors)
    on_fn = getattr(page, 'on', None)
    if callable(on_fn):
        def _on_page_console(msg: object) -> None:
            msg_type = getattr(msg, 'type', None)
            if callable(msg_type): msg_type = msg_type()
            if msg_type == 'error':
                text = getattr(msg, 'text', '')
                if callable(text): text = text()
                text_str = str(text)
                if not _is_benign(text_str): entry = f'console.error: {text_str}'; diagnostic_errors.append(entry) if entry not in diagnostic_errors else None
        def _on_page_error(err: object) -> None:
            text_str = str(getattr(err, 'error', err))
            if not _is_benign(text_str): entry = f'pageerror: {text_str}'; diagnostic_errors.append(entry) if entry not in diagnostic_errors else None
        on_fn('console', _on_page_console); on_fn('pageerror', _on_page_error)
    orig_close = getattr(page, 'close', None)
    if callable(orig_close) and (not getattr(page, '_e2e_close_wrapped', False)):
        async def _wrapped_page_close(*args, **kwargs): await _capture_page_failure_diagnostics(item, page) if sys.exc_info()[0] is not None or getattr(item, '_e2e_test_failed', False) else None; return await orig_close(*args, **kwargs)
        try: setattr(page, 'close', _wrapped_page_close); setattr(page, '_e2e_close_wrapped', True)
        except Exception as exc: logger.debug(f'Could not wrap page.close: {exc}')
class TestConfig: APP_URL = os.getenv('APP_URL') or os.getenv('FRONTEND_URL') or 'http://localhost:3000'; TEST_ENV = os.getenv('TEST_ENV', 'staging').lower(); EXPECTED_SHA = os.getenv('EXPECTED_SHA'); HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'; TIMEOUT_MS = int(os.getenv('TIMEOUT_MS', '30000')); SLOW_MO = int(os.getenv('SLOW_MO', '0')); STORAGE_STATE_PATH = ROOT / 'tests' / 'e2e' / '.auth' / 'state.json'
_strict_e2e_gates_enabled = lambda: os.getenv('STRICT_E2E_GATES', '').lower() in {'1', 'true', 'yes'}; is_strict_or_ci = lambda: _strict_e2e_gates_enabled() or os.getenv('CI') == 'true'
def _emit_session_line(session, line: str) -> None: reporter = session.config.pluginmanager.get_plugin('terminalreporter'); reporter.write_line(line) if reporter is not None else print(line, file=sys.stderr)
def pytest_sessionstart(session):
    'EPIC-008'
    if is_strict_or_ci():
        if TestConfig.TEST_ENV != 'local':
            pytest.exit('Fatal: EXPECTED_SHA must be explicitly set in CI, staging, and strict gate environments', returncode=1) if not TestConfig.EXPECTED_SHA else None; health_url = f"{TestConfig.APP_URL.rstrip('/')}/api/health"
            try:
                import ssl; import urllib.error; import urllib.request; ctx = ssl.create_default_context()
                if os.getenv('E2E_INSECURE_TLS', '').lower() in {'1', 'true', 'yes'}: ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(health_url, headers={'User-Agent': HANDSHAKE_USER_AGENT})
                with urllib.request.urlopen(req, timeout=10.0, context=ctx) as resp: payload = json.loads(resp.read().decode('utf-8')); live_sha = payload.get('git_sha'); pytest.exit(f'Fatal: Stale target environment detected at {health_url}: expected SHA {TestConfig.EXPECTED_SHA}, but target serves {live_sha}', returncode=1) if live_sha != TestConfig.EXPECTED_SHA else None
            except urllib.error.HTTPError as err: pytest.exit(f'Fatal: Target health check failed with status {err.code} at {health_url}: {err.reason}', returncode=1)
            except Exception as exc:
                if isinstance(exc, pytest.exit.Exception): raise
                pytest.exit(f'Fatal: Could not connect to target environment at {health_url}: {exc}', returncode=1)
            else: report_path_quality(health_url, ctx, lambda line: _emit_session_line(session, line))
def format_ai_ocr_gate_failure(message: str, *, statement: dict | None=None, model: str | None=None) -> str:
    details: list[str] = []; details.append(f'model={model}') if model else None
    if statement:
        for key in ('id', 'status', 'validation_error', 'confidence_score', 'parsing_progress', 'balance_validated'): value = statement.get(key); details.append(f'{key}={value}') if value not in (None, '') else None
    if not details: return message
    return f'{message}. Details: ' + '; '.join(details)
def fail_or_skip_ai_ocr_gate(message: str, *, statement: dict | None=None, model: str | None=None) -> None: failure_message = format_ai_ocr_gate_failure(message, statement=statement, model=model); pytest.fail(failure_message) if _strict_e2e_gates_enabled() else None; pytest.skip(f'{failure_message} STRICT_E2E_GATES is not enabled for this environment.')
def _scrub_pytest_longrepr_node(node: object) -> bool:
    scrubbed = False; reprcrash = getattr(node, 'reprcrash', None)
    if reprcrash is not None and isinstance(getattr(reprcrash, 'message', None), str): reprcrash.message = redact_playwright_auth_headers(reprcrash.message); scrubbed = True
    reprtraceback = getattr(node, 'reprtraceback', None); reprentries = getattr(reprtraceback, 'reprentries', None)
    if isinstance(reprentries, list):
        for entry in reprentries:
            lines = getattr(entry, 'lines', None)
            if isinstance(lines, list): entry.lines = [redact_playwright_auth_headers(line) if isinstance(line, str) else line for line in lines]; scrubbed = True
            entry_reprcrash = getattr(entry, 'reprfileloc', None)
            if entry_reprcrash is not None and isinstance(getattr(entry_reprcrash, 'message', None), str): entry_reprcrash.message = redact_playwright_auth_headers(entry_reprcrash.message); scrubbed = True
    chain = getattr(node, 'chain', None)
    if isinstance(chain, list):
        for element in chain:
            if isinstance(element, tuple):
                for part in element:
                    if part is not None and _scrub_pytest_longrepr_node(part): scrubbed = True
    return scrubbed
def _scrub_report_longrepr(report: object) -> None:
    longrepr = getattr(report, 'longrepr', None)
    if longrepr is None: return
    if isinstance(longrepr, str): setattr(report, 'longrepr', redact_playwright_auth_headers(longrepr)); return
    if isinstance(longrepr, tuple) and len(longrepr) == 3 and isinstance(longrepr[2], str): setattr(report, 'longrepr', (longrepr[0], longrepr[1], redact_playwright_auth_headers(longrepr[2]))); return
    _scrub_pytest_longrepr_node(longrepr); longreprtext = getattr(report, 'longreprtext', None)
    if isinstance(longreprtext, str): redacted_text = redact_playwright_auth_headers(longreprtext); setattr(report, 'longrepr', redacted_text) if redacted_text != longreprtext else None
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = (yield); report = outcome.get_result()
    if should_convert_skip_to_failure(strict_gates_enabled=_strict_e2e_gates_enabled(), skipped=report.skipped, has_critical_marker=item.get_closest_marker(CRITICAL_MARKER) is not None, when=report.when): report.outcome = 'failed'; report.longrepr = critical_skip_failure_message(item.nodeid)
    rate_limit_hits = getattr(item, '_e2e_rate_limit_hits', []); already_reported = getattr(item, '_e2e_rate_limit_reported', False); setattr(item, '_e2e_rate_limit_reported', True) if report.when in {'call', 'teardown'} and rate_limit_hits and (not already_reported) and fail_report_for_rate_limits(report, rate_limit_hits) else None; _scrub_report_longrepr(report)
    if getattr(report, 'failed', False) or getattr(report, 'outcome', '') == 'failed':
        setattr(item, '_e2e_test_failed', True)
        if not getattr(item, '_e2e_diagnostics_captured', False) and getattr(item, '_e2e_pages', None):
            try: loop = asyncio.get_event_loop(); loop.run_until_complete(_capture_page_failure_diagnostics(item)) if not loop.is_running() and (not loop.is_closed()) else None
            except Exception as exc: logger.debug(f'makereport diagnostic capture skipped: {exc}')
class AuthState: user_id: str | None = None; email: str | None = None; access_token: str | None = None; password: str | None = None
def auth_cookie(access_token: str) -> dict[str, object]:
    try: return build_auth_cookie(TestConfig.APP_URL, access_token)
    except ValueError as exc: pytest.fail(str(exc))
@pytest.fixture(scope='session')
def repo_root() -> Path: return ROOT
@pytest.fixture(scope='session')
def config() -> TestConfig: return TestConfig()
@pytest.fixture(scope='session')
def event_loop(): loop = asyncio.new_event_loop(); yield loop; loop.close()
@pytest.fixture(scope='session')
async def shared_auth_state() -> AsyncGenerator[AuthState, None]:
    import httpx; state = AuthState(); unique_id = uuid.uuid4().hex[:8]; state.email = f'e2e-session-{unique_id}@test.example.com'; state.password = 'E2ESessionPassword123!'; logger.info(f'[SESSION SETUP] Creating shared test user: {state.email}'); api_url = TestConfig.APP_URL.rstrip('/')
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(f'{api_url}/api/auth/register', json={'email': state.email, 'password': state.password}); pytest.fail(f'[SESSION SETUP] Failed to register shared user: {response.status_code} - {response.text}') if response.status_code not in (200, 201) else None
            try: data = response.json()
            except ValueError as e: pytest.fail(f'[SESSION SETUP] API returned invalid JSON: {response.text[:200]}... Error: {e}')
            pytest.fail(f'[SESSION SETUP] API returned non-dict: {type(data).__name__}') if not isinstance(data, dict) else None; state.user_id = data.get('id'); state.access_token = data.get('access_token'); pytest.fail(f'[SESSION SETUP] Registration response missing id or access_token. Got keys: {list(data.keys())}') if not state.user_id or not state.access_token else None; logger.info(f'[SESSION SETUP] Shared user created: {state.user_id}')
    except httpx.RequestError as e: pytest.fail(f'[SESSION SETUP] Failed to connect to backend: {e}')
    yield state; logger.info(f'[SESSION TEARDOWN] Cleaning up shared test user: {state.user_id}')
    if state.user_id and state.access_token:
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client: delete_response = await client.delete(f'{api_url}/api/users/{state.user_id}', headers={'Authorization': f'Bearer {state.access_token}'}); logger.info('[SESSION TEARDOWN] Shared user cleaned up successfully') if delete_response.status_code in (200, 204) else logger.debug(f'[SESSION TEARDOWN] DELETE /api/users endpoint not found (status 404). Shared user {state.user_id} will remain in database.') if delete_response.status_code == 404 else logger.warning(f'[SESSION TEARDOWN] Failed to cleanup shared user: status {delete_response.status_code}')
        except Exception as e: logger.debug(f'[SESSION TEARDOWN] Cleanup error (non-critical): {e}')
@pytest.fixture
async def browser() -> AsyncGenerator[Browser, None]:
    async with async_playwright() as p: browser = await p.chromium.launch(headless=TestConfig.HEADLESS, slow_mo=TestConfig.SLOW_MO); yield browser; await browser.close()
_BENIGN_BROWSER_NOISE = ('cloudflareinsights.com', 'static.cloudflareinsights.com')
def _is_csp_violation(text: str) -> bool: t = text.lower(); return 'content security policy' in t or 'content-security-policy' in t
_is_benign = lambda text: any((n in text for n in _BENIGN_BROWSER_NOISE))
@pytest.fixture
async def context(browser: Browser, request: pytest.FixtureRequest) -> AsyncGenerator[BrowserContext, None]:
    context = await browser.new_context(ignore_https_errors=True, viewport={'width': 1280, 'height': 720}, base_url=TestConfig.APP_URL); csp_violations: list[str] = []; page_errors: list[str] = []; diagnostic_errors: list[str] = []; rate_limit_hits: list[RateLimitHit] = []; setattr(request.node, '_e2e_rate_limit_hits', rate_limit_hits); setattr(request.node, '_e2e_diagnostic_errors', diagnostic_errors); setattr(request.node, '_e2e_pages', [])
    def _on_console(msg) -> None:
        msg_type = getattr(msg, 'type', None)
        if callable(msg_type): msg_type = msg_type()
        if msg_type == 'error':
            text = getattr(msg, 'text', '')
            if callable(text): text = text()
            text_str = str(text)
            if not _is_benign(text_str): entry = f'console.error: {text_str}'; diagnostic_errors.append(entry) if entry not in diagnostic_errors else None; csp_violations.append(text_str) if _is_csp_violation(text_str) else None
    def _on_weberror(err) -> None:
        text = str(getattr(err, 'error', err))
        if not _is_benign(text): page_errors.append(text); entry = f'pageerror: {text}'; diagnostic_errors.append(entry) if entry not in diagnostic_errors else None
    def _on_response(response) -> None: record_rate_limit_response(response, rate_limit_hits)
    context.on("console", _on_console); context.on("weberror", _on_weberror); context.on('response', _on_response); orig_new_page = getattr(context, 'new_page', None)
    if callable(orig_new_page):
        async def _wrapped_new_page(*args, **kwargs): new_page_obj = await orig_new_page(*args, **kwargs); _attach_page_diagnostics(request.node, new_page_obj); return new_page_obj
        try: setattr(context, 'new_page', _wrapped_new_page)
        except Exception as exc: logger.debug(f'Could not wrap context.new_page: {exc}')
    orig_context_close = getattr(context, 'close', None)
    if callable(orig_context_close) and (not getattr(context, '_e2e_close_wrapped', False)):
        async def _wrapped_context_close(*args, **kwargs): await _capture_page_failure_diagnostics(request.node) if sys.exc_info()[0] is not None or getattr(request.node, '_e2e_test_failed', False) else None; return await orig_context_close(*args, **kwargs)
        try: setattr(context, 'close', _wrapped_context_close); setattr(context, '_e2e_close_wrapped', True)
        except Exception as exc: logger.debug(f'Could not wrap context.close: {exc}')
    yield context; invariant_failed = request.node.get_closest_marker('allow_browser_errors') is None and bool(csp_violations or page_errors); await _capture_page_failure_diagnostics(request.node) if invariant_failed or sys.exc_info()[0] is not None or getattr(request.node, '_e2e_test_failed', False) else None; await context.close()
    if request.node.get_closest_marker('allow_browser_errors'): return
    assert not csp_violations, 'CSP violation(s) during this test — a script the app loads is blocked by its own Content-Security-Policy:\n  ' + '\n  '.join(csp_violations[:5]); assert not page_errors, 'Uncaught JS error(s) on a visited page:\n  ' + '\n  '.join(page_errors[:5])
@pytest.fixture
async def page(context: BrowserContext, request: pytest.FixtureRequest) -> AsyncGenerator[Page, None]:
    page = await context.new_page(); _attach_page_diagnostics(request.node, page); page.set_default_timeout(TestConfig.TIMEOUT_MS)
    try: yield page
    finally: await _capture_page_failure_diagnostics(request.node, page) if sys.exc_info()[0] is not None or getattr(request.node, '_e2e_test_failed', False) else None; await page.close()
@pytest.fixture
async def authenticated_page(context: BrowserContext, shared_auth_state: AuthState, request: pytest.FixtureRequest) -> AsyncGenerator[Page, None]:
    page = await context.new_page(); _attach_page_diagnostics(request.node, page); page.set_default_timeout(TestConfig.TIMEOUT_MS); logger.info(f'Setting up authenticated page for user: {shared_auth_state.user_id}')
    try:
        import jwt; decoded = jwt.decode(shared_auth_state.access_token, options={'verify_signature': False}); exp_timestamp = decoded.get('exp')
        if exp_timestamp: time_until_expiry = exp_timestamp - datetime.now().timestamp(); logger.warning(f'Token expires in {time_until_expiry:.0f}s, test may fail for long runs') if time_until_expiry < 300 else None
    except ImportError: pass
    except Exception as e: logger.debug(f'Token expiration check failed: {e}')
    await context.add_cookies([auth_cookie(str(shared_auth_state.access_token))]); await context.add_init_script(f"\n        localStorage.setItem('finance_user_id', {json.dumps(str(shared_auth_state.user_id))});\n        localStorage.setItem('finance_user_email', {json.dumps(shared_auth_state.email)});\n    "); logger.info('Auth cookie and user metadata injected'); await page.goto(f'{TestConfig.APP_URL}/dashboard', wait_until='domcontentloaded'); await page.wait_for_load_state('domcontentloaded'); pytest.fail(f'authenticated_page fixture failed: redirected to login. Current URL: {page.url}. Check if auth cookie and user metadata are being properly injected.') if '/login' in page.url else None; logger.info('Authentication verified successfully')
    try: yield page
    finally: await _capture_page_failure_diagnostics(request.node, page) if sys.exc_info()[0] is not None or getattr(request.node, '_e2e_test_failed', False) else None; await page.close()
@pytest.fixture
async def authenticated_page_unique(context: BrowserContext, request: pytest.FixtureRequest) -> AsyncGenerator[Page, None]:
    import httpx; page = await context.new_page(); _attach_page_diagnostics(request.node, page); page.set_default_timeout(TestConfig.TIMEOUT_MS); unique_id = uuid.uuid4().hex[:8]; test_email = f'e2e-unique-{unique_id}@test.example.com'; test_password = 'E2EUniquePassword123!'; logger.info(f'Creating UNIQUE test user: {test_email}'); api_url = TestConfig.APP_URL.rstrip('/'); user_id = None; access_token = None
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(f'{api_url}/api/auth/register', json={'email': test_email, 'password': test_password}); pytest.fail(f'Failed to register test user: {response.status_code} - {response.text}') if response.status_code not in (200, 201) else None
            try: data = response.json()
            except ValueError as e: pytest.fail(f'API returned invalid JSON: {response.text[:200]}... Error: {e}')
            pytest.fail(f'API returned non-dict: {type(data).__name__}') if not isinstance(data, dict) else None; user_id = data.get('id'); access_token = data.get('access_token'); pytest.fail(f'Registration response missing id or access_token. Got keys: {list(data.keys())}') if not user_id or not access_token else None; logger.info(f'User registered successfully: {user_id}')
            if request.node.get_closest_marker('product_defaults') is None: review_path = await client.patch(f'{api_url}/api/users/me/settings', json={'auto_accept_ai_suggestions': False}, headers={'Authorization': f'Bearer {access_token}'}); pytest.fail(f'Failed to put the test user on the review path: {review_path.status_code} - {review_path.text}') if review_path.status_code != 200 else None
    except httpx.RequestError as e: pytest.fail(f'Failed to connect to backend for user registration: {e}')
    try:
        import jwt; decoded = jwt.decode(access_token, options={'verify_signature': False}); exp_timestamp = decoded.get('exp')
        if exp_timestamp: time_until_expiry = exp_timestamp - datetime.now().timestamp(); logger.warning(f'Token expires in {time_until_expiry:.0f}s, test may fail for long runs') if time_until_expiry < 300 else None
    except ImportError: pass
    except Exception as e: logger.debug(f'Token expiration check failed: {e}')
    await context.add_cookies([auth_cookie(str(access_token))]); await context.add_init_script(f"\n        localStorage.setItem('finance_user_id', {json.dumps(str(user_id))});\n        localStorage.setItem('finance_user_email', {json.dumps(test_email)});\n    "); logger.info('Auth cookie and user metadata injected'); await page.goto(f'{TestConfig.APP_URL}/dashboard', wait_until='domcontentloaded'); await page.wait_for_load_state('domcontentloaded'); pytest.fail(f'authenticated_page fixture failed: redirected to login. Current URL: {page.url}. Check if auth cookie and user metadata are being properly injected.') if '/login' in page.url else None; logger.info('Authentication verified successfully')
    try: yield page
    finally:
        await _capture_page_failure_diagnostics(request.node, page) if sys.exc_info()[0] is not None or getattr(request.node, '_e2e_test_failed', False) else None; await page.close()
        if user_id and access_token:
            try:
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client: delete_response = await client.delete(f'{api_url}/api/users/{user_id}', headers={'Authorization': f'Bearer {access_token}'}); logger.info(f'Test user {user_id} cleaned up successfully') if delete_response.status_code in (200, 204) else logger.debug(f'DELETE /api/users endpoint not found (status 404). Test user {user_id} will remain in database. Consider implementing user cleanup endpoint.') if delete_response.status_code == 404 else logger.warning(f'Failed to cleanup test user {user_id}: status {delete_response.status_code}')
            except Exception as e: logger.debug(f'User cleanup error (non-critical): {e}')
