"""Shared E2E journey helpers for HTTP setup, statement polling, diagnostics, and pinning."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from common.testing import money_amount
from playwright.async_api import BrowserContext, Page, expect
from tests.benchmarks.run_financial_scenario_benchmark import ScenarioBenchmarkRunner
from tests.fixtures.provider_review import (
    FixtureDisposition,
    FixtureEnvelope,
    approve_statement_with_fixture_review,
)

from tests.e2e.auth_cookie import build_auth_cookie, redact_playwright_auth_headers
from tests.e2e.bench_ui_bridge import BenchUiBridge
from tests.e2e.deployment_pin import (
    assert_pinned_deployment,
    expected_version_from_env,
    resolve_expected_commit,
)
from tests.e2e.journey_checkpoint import checkpoint
from tests.e2e.path_quality import HANDSHAKE_USER_AGENT, report_path_quality
from tests.e2e.transport_retry import ReconnectCount, get_with_reconnect

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
PARSING_TIMEOUT_MS = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))
PAGE_TEXT_MAX_BYTES = 4096
_NODEID_UNSAFE_RE = re.compile("[^A-Za-z0-9._-]+")


class AuthState:
    user_id: str | None = None
    email: str | None = None
    access_token: str | None = None
    password: str | None = None


def get_url(path: str, base_url: str = APP_URL) -> str:
    return f"{base_url.rstrip('/')}{path}"


def api_url(path: str, base_url: str = APP_URL) -> str:
    return f"{base_url.rstrip('/')}/api{path}"


def verify_session_target(
    session: Any, *, app_url: str, expected_sha: str | None
) -> None:
    if not expected_sha:
        pytest.exit(
            "Fatal: EXPECTED_SHA or APP_VERSION_REF must be explicitly set in CI, staging, and strict gate environments",
            returncode=1,
        )
    health_url, ctx = api_url("/health", app_url), ssl.create_default_context()
    if os.getenv("E2E_INSECURE_TLS", "").lower() in {"1", "true", "yes"}:
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                health_url, headers={"User-Agent": HANDSHAKE_USER_AGENT}
            ),
            timeout=10.0,
            context=ctx,
        ) as resp:
            live_sha = json.loads(resp.read().decode("utf-8")).get("git_sha")
        if live_sha != expected_sha:
            pytest.exit(
                f"Fatal: Stale target environment at {health_url}: expected {expected_sha}, got {live_sha}",
                returncode=1,
            )
    except pytest.exit.Exception:
        raise
    except Exception as exc:
        pytest.exit(
            f"Fatal: Target health check failed at {health_url}: {exc}", returncode=1
        )
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    report_path_quality(
        health_url,
        ctx,
        lambda line: reporter.write_line(line)
        if reporter
        else print(line, file=sys.stderr),
    )


async def capture_page_failure_diagnostics(
    item: object, page: object | None = None
) -> Path | None:
    if getattr(item, "_e2e_diagnostics_captured", False):
        return getattr(item, "_e2e_diagnostics_dir", None)
    pages = list(getattr(item, "_e2e_pages", []))
    target = page or next(
        (p for p in reversed(pages) if not p.is_closed()), pages[-1] if pages else None
    )
    if target is None:
        return None
    setattr(item, "_e2e_diagnostics_captured", True)
    nodeid = (
        _NODEID_UNSAFE_RE.sub(
            "__", str(getattr(item, "nodeid", "unknown_test")).strip()
        ).strip("._-")
        or "unknown_test"
    )
    artifact_dir = (
        Path(
            os.getenv("E2E_FAILURE_ARTIFACT_DIR")
            or ROOT / "test-results" / "e2e-failures"
        )
        / nodeid
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    setattr(item, "_e2e_diagnostics_dir", artifact_dir)
    raw_text = ""
    try:
        shot = artifact_dir / "screenshot.png"
        data = await target.screenshot(path=str(shot), full_page=True)
        if not shot.exists() and isinstance(data, (bytes, bytearray)):
            shot.write_bytes(bytes(data))
        raw_text = await target.locator("body").inner_text(timeout=2000)
    except Exception:
        pass
    (artifact_dir / "page-text.txt").write_text(
        redact_playwright_auth_headers(raw_text)
        .encode("utf-8")[:PAGE_TEXT_MAX_BYTES]
        .decode("utf-8", errors="ignore"),
        encoding="utf-8",
    )
    (artifact_dir / "page-errors.txt").write_text(
        redact_playwright_auth_headers(
            "\n".join(getattr(item, "_e2e_diagnostic_errors", []))
        ),
        encoding="utf-8",
    )
    return artifact_dir


def scrub_report_longrepr(report: object) -> None:
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, str):
        report.longrepr = redact_playwright_auth_headers(longrepr)  # type: ignore[attr-defined]
    elif (
        isinstance(longrepr, tuple)
        and len(longrepr) == 3
        and isinstance(longrepr[2], str)
    ):
        report.longrepr = (
            longrepr[0],
            longrepr[1],
            redact_playwright_auth_headers(longrepr[2]),
        )  # type: ignore[attr-defined]
    elif (
        isinstance(text := getattr(report, "longreprtext", None), str)
        and (redacted := redact_playwright_auth_headers(text)) != text
    ):
        report.longrepr = redacted  # type: ignore[attr-defined]


async def register_e2e_user(
    base_url: str, prefix: str, *, disable_auto_accept: bool = False
) -> AuthState:
    state = AuthState()
    state.email, state.password = (
        f"{prefix}-{uuid.uuid4().hex[:8]}@test.example.com",
        "E2ETestPassword123!",
    )
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.post(
                api_url("/auth/register", base_url),
                json={"email": state.email, "password": state.password},
            )
            assert resp.status_code in (200, 201), (
                f"Failed to register {prefix} user: {resp.status_code} - {resp.text}"
            )
            data = resp.json()
            state.user_id, state.access_token = data.get("id"), data.get("access_token")
            assert state.user_id and state.access_token, (
                f"Registration response invalid: {data}"
            )
            if disable_auto_accept:
                settings = await client.patch(
                    api_url("/users/me/settings", base_url),
                    json={"auto_accept_ai_suggestions": False},
                    headers={"Authorization": f"Bearer {state.access_token}"},
                )
                assert settings.status_code == 200, (
                    f"Failed to put user on review path: {settings.status_code} - {settings.text}"
                )
    except Exception as exc:
        pytest.fail(str(exc))
    return state


async def delete_e2e_user(base_url: str, state: AuthState) -> None:
    if state.user_id and state.access_token:
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                await client.delete(
                    api_url(f"/users/{state.user_id}", base_url),
                    headers={"Authorization": f"Bearer {state.access_token}"},
                )
        except Exception as exc:
            logger.debug(f"User cleanup error (non-critical): {exc}")


async def open_authenticated_page(
    context: BrowserContext,
    request: pytest.FixtureRequest,
    state: AuthState,
    *,
    base_url: str,
    timeout_ms: int,
) -> Page:
    page = await context.new_page()
    request.node._e2e_pages.append(page)
    page.set_default_timeout(timeout_ms)
    try:
        cookie = build_auth_cookie(base_url, str(state.access_token))
    except ValueError as exc:
        pytest.fail(str(exc))
    await context.add_cookies([cookie])
    await context.add_init_script(
        f"localStorage.setItem('finance_user_id', {json.dumps(str(state.user_id))});localStorage.setItem('finance_user_email', {json.dumps(state.email)});"
    )
    await page.goto(f"{base_url}/dashboard", wait_until="domcontentloaded")
    await page.wait_for_load_state("domcontentloaded")
    if "/login" in page.url:
        pytest.fail(
            f"authenticated_page fixture failed: redirected to login. URL: {page.url}"
        )
    return page


async def auth_headers(page: Page, base_url: str = APP_URL) -> dict[str, str]:
    cookie = next(
        (
            c
            for c in await page.context.cookies(base_url)
            if c["name"] == "finance_access_token"
        ),
        None,
    )
    assert cookie, "authenticated Playwright context is missing auth cookie"
    return {"Cookie": f"finance_access_token={cookie['value']}"}


async def get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    base_url: str = APP_URL,
    reconnects: ReconnectCount | None = None,
    **params: Any,
) -> Any:
    url = api_url(path, base_url)
    resp = (
        await get_with_reconnect(client, url, reconnects, params=params or None)
        if reconnects is not None
        else await client.get(url, params=params or None)
    )
    assert resp.status_code == 200, f"GET {path} failed: {resp.status_code} {resp.text}"
    return resp.json()


async def post_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    json: Any = None,
    expected_status: tuple[int, ...] = (200, 201),
    base_url: str = APP_URL,
    label: str = "",
) -> Any:
    resp = await client.post(api_url(path, base_url), json=json)
    assert resp.status_code in expected_status, (
        f"POST {label or path} failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


async def assert_pinned_via_client(
    client: httpx.AsyncClient,
    record_property: Callable[[str, object], None],
    *,
    base_url: str = APP_URL,
    reconnects: ReconnectCount | None = None,
    reason: str = "core-journey proof",
) -> dict[str, Any]:
    expected_version = expected_version_from_env()
    assert expected_version, f"{reason} requires an explicit EXPECTED_SHA or APP_VERSION_REF"
    expected_commit = resolve_expected_commit(expected_version)
    health = await get_json(client, "/health", base_url=base_url, reconnects=reconnects)
    fe_url = get_url("/frontend-version.json", base_url)
    fe_resp = (
        await get_with_reconnect(client, fe_url, reconnects)
        if reconnects is not None
        else await client.get(fe_url)
    )
    assert fe_resp.status_code == 200, "frontend deployment version must be observable"
    fe_json = fe_resp.json()
    assert_pinned_deployment(health, expected_version, expected_commit)
    assert_pinned_deployment(fe_json, expected_version, expected_commit)
    assert fe_json.get("git_sha")
    for k, v in {
        "expected_version": expected_version,
        "expected_commit": expected_commit,
        "backend_version": health.get("git_sha"),
        "frontend_version": fe_json.get("git_sha"),
    }.items():
        record_property(k, v)
    checkpoint(record_property, "U12")
    return health


async def assert_pinned_via_page(
    page: Page,
    record_property: Callable[[str, object], None],
    *,
    base_url: str = APP_URL,
) -> None:
    expected_version = expected_version_from_env()
    assert expected_version, "live browser proof requires an explicit EXPECTED_SHA or APP_VERSION_REF"
    expected_commit = resolve_expected_commit(expected_version)
    for path in ("/api/health", "/frontend-version.json"):
        resp = await page.request.get(get_url(path, base_url))
        assert resp.status == 200
        payload = await resp.json()
        assert_pinned_deployment(payload, expected_version, expected_commit)
        record_property(path, payload["git_sha"])
    checkpoint(record_property, "U12")


async def assert_default_ai_settings(client: httpx.AsyncClient) -> None:
    settings = await get_json(client, "/users/me/settings")
    assert (
        settings["enable_ai_classification"] is True
        and settings["auto_accept_ai_suggestions"] is True
        and settings["auto_accept_ai_suggestions_active"] is True
    )


async def default_image_model(
    client: httpx.AsyncClient,
    *,
    base_url: str = APP_URL,
    reconnects: ReconnectCount | None = None,
) -> str:
    payload = await get_json(
        client,
        "/llm/catalog",
        base_url=base_url,
        reconnects=reconnects,
        modality="image",
    )
    return payload.get("default_model") or payload["models"][0]["id"]


def unique_pdf_copy(src: Path) -> Path:
    dest = (
        Path(tempfile.mkdtemp())
        / f"{src.stem}_{int(time.time() * 1000) % 1000000}{src.suffix}"
    )
    shutil.copy2(src, dest)
    with dest.open("ab") as fh:
        fh.write(f"\n%% E2E test run {uuid.uuid4()}\n".encode())
    return dest


async def upload_statement(
    client: httpx.AsyncClient,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    institution: str | None = None,
    account_id: str | None = None,
    model: str | None = None,
    base_url: str = APP_URL,
    label: str = "statement",
) -> str:
    data = {
        k: v
        for k, v in (
            ("institution", institution),
            ("account_id", account_id),
            ("model", model),
        )
        if v is not None
    }
    resp = await client.post(
        api_url("/statements", base_url),
        data=data,
        files={"file": (filename, content, content_type)},
    )
    assert resp.status_code in (200, 201, 202) and (sid := resp.json().get("id")), (
        f"{label} upload failed: {resp.status_code} {resp.text}"
    )
    return str(sid)


async def wait_for_statement(
    client: httpx.AsyncClient,
    statement_id: str,
    *,
    timeout_ms: int = PARSING_TIMEOUT_MS,
    poll_seconds: float = 2.0,
    target_statuses: tuple[str, ...] = ("parsed", "approved"),
    fail_statuses: tuple[str, ...] = ("rejected",),
    gate_name: str | None = None,
    model: str | None = None,
    require_transactions: bool = False,
    reconnects: ReconnectCount | None = None,
    base_url: str = APP_URL,
    timeout_formatter: Callable[[str, dict | None], str] | None = None,
) -> dict[str, Any]:
    from tests.e2e.conftest import fail_or_skip_ai_ocr_gate

    deadline, last_payload = asyncio.get_running_loop().time() + timeout_ms / 1000, None
    while asyncio.get_running_loop().time() < deadline:
        last_payload = await get_json(
            client,
            f"/statements/{statement_id}",
            base_url=base_url,
            reconnects=reconnects,
        )
        status = last_payload.get("status")
        if status in fail_statuses:
            if gate_name is not None:
                fail_or_skip_ai_ocr_gate(
                    f"{gate_name} gate rejected statement {statement_id}: {last_payload.get('validation_error')}",
                    statement=last_payload,
                    model=model,
                )
            pytest.fail(
                f"statement {statement_id} ended in {status}: {last_payload.get('validation_error')}"
            )
        if status in target_statuses:
            assert not require_transactions or last_payload.get("transactions"), (
                f"parsed statement {statement_id} has no transactions: {last_payload}"
            )
            return last_payload
        await asyncio.sleep(poll_seconds)
    pytest.fail(
        timeout_formatter(statement_id, last_payload)
        if timeout_formatter
        else f"statement {statement_id} did not reach {target_statuses} within {timeout_ms}ms; last payload: {last_payload}"
    )


async def poll_statement_via_page(
    page: Page,
    statement_id: str,
    *,
    timeout_ms: int = PARSING_TIMEOUT_MS,
    poll_ms: int = 2000,
    target_statuses: tuple[str, ...] = ("parsed", "approved", "rejected"),
    base_url: str = APP_URL,
) -> dict[str, Any]:
    deadline, last = asyncio.get_running_loop().time() + timeout_ms / 1000, None
    while asyncio.get_running_loop().time() < deadline:
        resp = await page.request.get(
            get_url(f"/api/statements/{statement_id}", base_url)
        )
        assert resp.status == 200, await resp.text()
        last = await resp.json()
        if last.get("status") in target_statuses:
            return last
        await page.wait_for_timeout(poll_ms)
    pytest.fail(
        f"statement {statement_id} never reached {target_statuses} within {timeout_ms}ms; last={last}"
    )


async def upload_parse_and_approve_csv(
    client: httpx.AsyncClient,
    *,
    filename: str,
    csv_bytes: bytes,
    institution: str,
    dispositions: dict[str, FixtureDisposition],
    envelope: FixtureEnvelope,
    account_id: str | None = None,
    expected_txns: int | None = None,
    poll_seconds: float = 0.5,
    target_statuses: tuple[str, ...] = ("parsed", "approved", "rejected"),
    fail_statuses: tuple[str, ...] = (),
    reconnects: ReconnectCount | None = None,
    get: Callable[[str], Awaitable[httpx.Response]] | None = None,
) -> tuple[str, dict[str, Any]]:
    stmt_id = await upload_statement(
        client,
        filename=filename,
        content=csv_bytes,
        content_type="text/csv",
        institution=institution,
        account_id=account_id,
        label=institution,
    )
    parsed = await wait_for_statement(
        client,
        stmt_id,
        poll_seconds=poll_seconds,
        target_statuses=target_statuses,
        fail_statuses=fail_statuses,
        reconnects=reconnects,
    )
    if expected_txns is not None:
        assert len(parsed["transactions"]) == expected_txns
    if parsed.get("status") != "approved":
        approval = await approve_statement_with_fixture_review(
            client,
            api_url=api_url,
            statement_id=stmt_id,
            transactions=parsed["transactions"],
            dispositions=dispositions,
            envelope=envelope,
            get=get,
        )
        assert approval["status"] == "approved"
    return stmt_id, parsed


async def upload_statement_via_ui(
    page: Page,
    *,
    institution: str,
    file_path: Path,
    csv_mode: bool = False,
    select_model: bool = True,
    base_url: str = APP_URL,
) -> str:
    await page.goto(get_url("/upload", base_url), wait_until="domcontentloaded")
    container = (
        page.locator("details").filter(has_text="CSV import") if csv_mode else page
    )
    if csv_mode:
        await container.locator("summary").click()
        await container.locator('[data-testid="uploader-institution-csv"]').fill(
            institution
        )
        await page.set_input_files('[data-testid="uploader-file-csv"]', str(file_path))
    else:
        await page.locator('[data-testid="uploader-institution-statement"]').fill(
            institution
        )
        await page.set_input_files(
            '[data-testid="uploader-file-statement"]', str(file_path)
        )
    await expect(
        container.locator("p.font-medium", has_text=file_path.name)
    ).to_be_visible(timeout=10000)
    async with page.expect_response(
        lambda r: r.request.method == "POST"
        and r.url.split("?", 1)[0].endswith("/api/statements"),
        timeout=60000,
    ) as info:
        await container.get_by_role("button", name="Upload & Parse Statement").click()
    resp = await info.value
    assert resp.status in (200, 201, 202) and (sid := (await resp.json()).get("id")), (
        f"Upload failed: {resp.status}"
    )
    return str(sid)


async def setup_runner_page(
    page: Page,
    prefix: str,
    accounts: tuple[tuple[str, str], ...],
    *,
    csv_bytes: bytes | None = None,
    base_url: str = APP_URL,
) -> str | None:
    runner = ScenarioBenchmarkRunner(base_url=base_url, timeout=120.0)
    client, _, _ = runner.create_ephemeral_client(prefix)
    for name, acc_type in accounts:
        runner.create_account(client, name=name, type=acc_type, currency="SGD")
    stmt_id = None
    if csv_bytes is not None:
        stmt_id = runner.upload_statement(client, csv_bytes, "operations.csv")
        runner.wait_for_statement_parsed(client, stmt_id)
    assert runner.last_auth_context is not None
    await BenchUiBridge.inject_runner_session_to_browser(
        page, runner.last_auth_context, base_url
    )
    return stmt_id


async def create_account(
    client: httpx.AsyncClient,
    name: str,
    *,
    account_type: str = "ASSET",
    currency: str = "SGD",
    base_url: str = APP_URL,
) -> str:
    return str(
        (
            await post_json(
                client,
                "/accounts",
                json={"name": name, "type": account_type, "currency": currency},
                expected_status=(201,),
                base_url=base_url,
                label=f"account {name}",
            )
        )["id"]
    )


async def create_opening_balances(
    client: httpx.AsyncClient,
    *,
    entry_date: str,
    balances: dict[str, str],
    currency: str = "SGD",
    memo: str = "",
    base_url: str = APP_URL,
) -> dict[str, Any]:
    return await post_json(
        client,
        "/accounts/opening-balances",
        json={
            "entry_date": entry_date,
            "balances": balances,
            "currency": currency,
            "memo": memo,
        },
        expected_status=(201,),
        base_url=base_url,
        label="opening balances",
    )


async def create_manual_valuation(
    client: httpx.AsyncClient,
    *,
    component_type: str,
    as_of_date: date,
    value: Decimal,
    source: str,
    currency: str = "SGD",
    notes: str | None = None,
    base_url: str = APP_URL,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "component_type": component_type,
        "as_of_date": as_of_date.isoformat(),
        "value": str(value),
        "currency": currency,
        "source": source,
    }
    if notes is not None:
        payload["notes"] = notes
    return await post_json(
        client,
        "/pricing/manual-valuations",
        json=payload,
        expected_status=(201,),
        base_url=base_url,
        label=f"manual valuation {component_type}",
    )


async def reconcile_twice_and_assert_clean(
    client: httpx.AsyncClient, statement_id: str, *, base_url: str = APP_URL
) -> None:
    for _ in range(2):
        assert await post_json(
            client,
            "/reconciliation/runs",
            json={"statement_id": statement_id},
            expected_status=(200,),
            base_url=base_url,
        ) == {
            "matches_created": 0,
            "auto_accepted": 0,
            "pending_review": 0,
            "unmatched": 0,
        }
    queue = await get_json(client, "/reconciliation/review-queue", base_url=base_url)
    assert queue["pending_matches"] == [] and queue["has_unresolved_checks"] is False


async def import_brokerage_and_holdings(
    client: httpx.AsyncClient, statement_id: str, *, base_url: str = APP_URL
) -> tuple[int, list[dict[str, Any]]]:
    imp = await post_json(
        client,
        "/portfolio/brokerage-imports",
        json={"statement_id": statement_id},
        expected_status=(200,),
        base_url=base_url,
        label="brokerage import",
    )
    assert imp["parsed_positions"] > 0, f"no brokerage positions imported: {imp}"
    holdings = (await get_json(client, "/portfolio/holdings", base_url=base_url))[
        "items"
    ]
    assert len(holdings) >= imp["parsed_positions"], (
        f"missing imported holdings: {holdings}"
    )
    return imp["parsed_positions"], holdings


def line_total(lines: list[dict[str, Any]], token: str | None = None) -> Decimal:
    filtered = (
        lines
        if token is None
        else [
            line for line in lines if token.lower() in str(line.get("name", "")).lower()
        ]
    )
    return money_amount(
        sum(
            (money_amount(line.get("amount", "0")) for line in filtered),
            Decimal("0.00"),
        )
    )


def assert_statement_rows_equal(
    actual_txns: list[dict[str, Any]], expected_events: list[dict[str, Any]]
) -> None:
    assert sorted(
        (t["txn_date"], Decimal(str(t["amount"])), t["direction"], t["currency"])
        for t in actual_txns
    ) == sorted(
        (e["date"], Decimal(e["amount"]), e["direction"], e["currency"])
        for e in expected_events
    )


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str


def recording_hook(requests: list[RecordedRequest]):
    async def record(request: httpx.Request) -> None:
        requests.append(RecordedRequest(request.method, request.url.path))

    return record
