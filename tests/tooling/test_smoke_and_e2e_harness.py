"""Smoke script, test DB reaper, E2E auto-accept poller, version check pin, PDF oracle, and FX seeding."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import subprocess
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import httpx
import pytest
from _pytest.outcomes import Failed
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = str(ROOT / "apps/backend")
for _p in (str(ROOT), _BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.testing import reap_test_dbs as rtd  # noqa: E402
from src.identity.base.types.auth import LoginRequest  # noqa: E402
from tests.benchmarks import pdf_corpus_oracle as oracle_mod  # noqa: E402
from tests.e2e import pdf_fixture_paths  # noqa: E402
from tests.e2e import test_version_check as version_check_mod  # noqa: E402
from tests.e2e.auto_accept_poll import wait_for_auto_approved_statement  # noqa: E402
from tests.e2e.deployment_pin import expected_version_from_env  # noqa: E402

SMOKE_SCRIPT = ROOT / "common/runtime/shell/smoke_test.sh"
VERSION_CHECK_COMMIT = "962a038f0629ad1db0860f2e9a2cb6a063cd97c1"


class _SmokeStubServer:
    def __init__(
        self,
        health_payload: dict[str, Any],
        *,
        statements_status: int = 401,
        include_cors_header: bool = True,
    ) -> None:
        self.health_payload = health_payload
        self.statements_status = statements_status
        self.include_cors_header = include_cors_header
        self.requests: list[tuple[str, str]] = []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def do_OPTIONS(self) -> None:
                parent.requests.append(("OPTIONS", self.path))
                self.send_response(200)
                if parent.include_cors_header:
                    self.send_header(
                        "Access-Control-Allow-Origin", self.headers.get("Origin", "*")
                    )
                self.end_headers()

            def do_GET(self) -> None:
                parent.requests.append(("GET", self.path))
                parsed = urlparse(self.path)
                if parsed.path == "/api/health":
                    body = json.dumps(parent.health_payload).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if parsed.path == "/api/statements":
                    body = (
                        b'{"status":"unexpected-public"}'
                        if parent.statements_status == 200
                        else b'{"detail":"Not authenticated"}'
                    )
                    self.send_response(parent.statements_status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                parent.requests.append(("POST", self.path))
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                if self.path == "/api/auth/login":
                    try:
                        payload = json.loads(raw_body.decode("utf-8"))
                        LoginRequest.model_validate(payload)
                    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
                        body = b'{"detail":"Validation error"}'
                        self.send_response(422)
                    else:
                        body = b'{"detail":"Invalid email or password"}'
                        self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> _SmokeStubServer:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def _head_sha(*, short: bool = False) -> str:
    args = ["git", "rev-parse", *(["--short=7"] if short else []), "HEAD"]
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def _run_smoke(
    base_url: str, *args: str, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"APP_VERSION_REF", "ENVIRONMENT", "MIN_CHECKS"}
    }
    env = {
        **clean_env,
        "SMOKE_READY_ATTEMPTS": "2",
        "SMOKE_READY_SLEEP_SECONDS": "0",
        **(env_overrides or {}),
    }
    return subprocess.run(
        ["bash", str(SMOKE_SCRIPT), base_url, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _healthy_payload(sha: str) -> dict[str, Any]:
    return {
        "status": "healthy",
        "git_sha": sha,
        "checks": {
            "database": {"status": "present", "required": True},
            "object_storage": {"status": "present", "required": True},
            "llm": {"status": "present", "required": True},
            "market_data": {"status": "present", "required": True},
        },
    }


def test_smoke_script_modes_dependencies_sha_and_failure_gates() -> None:
    sha = _head_sha()
    short7 = _head_sha(short=True)

    with _SmokeStubServer(_healthy_payload(sha)) as srv:
        prod = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha},
        )
    assert prod.returncode == 0, prod.stdout + prod.stderr
    assert not any(method == "POST" for method, _ in srv.requests)
    assert any(path == "/api/health?full=1" for _, path in srv.requests)

    with _SmokeStubServer(_healthy_payload(sha)) as srv:
        stg = _run_smoke(
            srv.base_url,
            env_overrides={"ENVIRONMENT": "staging", "APP_VERSION_REF": sha},
        )
    assert stg.returncode == 0, stg.stdout + stg.stderr
    assert ("POST", "/api/auth/login") in srv.requests

    no_md = _healthy_payload(sha)
    del no_md["checks"]["market_data"]
    with _SmokeStubServer(no_md) as srv:
        failed = _run_smoke(
            srv.base_url,
            env_overrides={"ENVIRONMENT": "staging", "APP_VERSION_REF": sha},
        )
    assert failed.returncode == 1 and "market_data" in failed.stdout

    bad_dep = _healthy_payload(sha)
    bad_dep["checks"]["llm"] = {"status": "absent", "required": True}
    with _SmokeStubServer(bad_dep) as srv:
        dep_res = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha},
        )
    assert dep_res.returncode == 1 and "llm" in dep_res.stdout

    with _SmokeStubServer(_healthy_payload("0000000")) as srv:
        mismatch = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha},
        )
    assert mismatch.returncode == 1 and "git_sha mismatch" in mismatch.stdout

    invalid_mode = _run_smoke(
        "http://127.0.0.1:9",
        "invalid-mode",
        env_overrides={"ENVIRONMENT": "development"},
    )
    assert invalid_mode.returncode == 2 and "Invalid MODE" in invalid_mode.stdout

    with _SmokeStubServer(_healthy_payload(sha)) as srv:
        local_dev = _run_smoke(
            f"{srv.base_url}/", env_overrides={"ENVIRONMENT": "local_dev"}
        )
    assert local_dev.returncode == 0 and ("POST", "/api/auth/login") in srv.requests

    with _SmokeStubServer(_healthy_payload(sha)) as srv:
        mixed_case = _run_smoke(
            f"{srv.base_url}/",
            "PREVIEW",
            env_overrides={"ENVIRONMENT": "Preview", "APP_VERSION_REF": sha},
        )
    assert mixed_case.returncode == 0

    with _SmokeStubServer(_healthy_payload(sha)) as srv:
        dev_mode = _run_smoke(
            srv.base_url, "dev", env_overrides={"ENVIRONMENT": "development"}
        )
    assert dev_mode.returncode == 0

    unknown_env = _run_smoke(
        "http://127.0.0.1:9", env_overrides={"ENVIRONMENT": "mystery-env"}
    )
    assert unknown_env.returncode == 2 and "Unknown ENVIRONMENT" in unknown_env.stdout

    with _SmokeStubServer(_healthy_payload(short7)) as srv:
        short_ok = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": "HEAD"},
        )
    assert short_ok.returncode == 0

    with _SmokeStubServer(_healthy_payload(sha[:6])) as srv:
        short_bad = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": "HEAD"},
        )
    assert short_bad.returncode == 1 and "git_sha mismatch" in short_bad.stdout

    with _SmokeStubServer(_healthy_payload(sha), statements_status=200) as srv:
        unprotected = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha},
        )
    assert unprotected.returncode == 1

    with _SmokeStubServer(_healthy_payload(sha), include_cors_header=False) as srv:
        no_cors = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha},
        )
    assert no_cors.returncode == 1

    with _SmokeStubServer(_healthy_payload(sha)) as srv:
        low_checks = _run_smoke(
            srv.base_url,
            "prod",
            env_overrides={
                "ENVIRONMENT": "production",
                "APP_VERSION_REF": sha,
                "MIN_CHECKS": "99",
            },
        )
    assert low_checks.returncode == 1

    bad_min = _run_smoke(
        "http://127.0.0.1:9",
        "prod",
        env_overrides={
            "ENVIRONMENT": "production",
            "APP_VERSION_REF": sha,
            "MIN_CHECKS": "abc",
        },
    )
    assert bad_min.returncode == 2


@pytest.mark.parametrize("env_name", ["preview", "pr-3224", "staging", "production"])
def test_smoke_script_requires_app_version_ref_in_deployed_envs(env_name: str) -> None:
    res = _run_smoke("http://127.0.0.1:9", env_overrides={"ENVIRONMENT": env_name})
    assert res.returncode == 2 and "APP_VERSION_REF" in res.stdout


def test_reap_orphaned_test_databases_and_lease_lifecycle(
    monkeypatch, tmp_path: Path
) -> None:
    from apps.backend.tests._support import db_isolation as ti

    monkeypatch.setattr(
        rtd,
        "list_test_databases",
        lambda **_kw: [
            "finance_report_test_preflight_111_gw0",
            "finance_report_test_preflight_222_gw0",
            "finance_report_test_mutation_333",
            "finance_report_test_planner_seq_abcd1234",
            "finance_report_test_busy_ns",
            "finance_report_test_active_ns",
        ],
    )
    monkeypatch.setattr(
        rtd, "list_active_databases", lambda **_kw: {"finance_report_test_busy_ns"}
    )
    monkeypatch.setattr(rtd, "load_active_namespaces", lambda: ["active_ns"])
    monkeypatch.setattr(
        rtd.os,
        "kill",
        lambda pid, _sig: None
        if pid == 111
        else (_ for _ in ()).throw(ProcessLookupError()),
    )
    dropped: list[str] = []
    monkeypatch.setattr(
        rtd, "drop_database", lambda db_name, **_kw: dropped.append(db_name) or True
    )
    reaped, total = rtd.reap_orphaned_test_databases()
    assert (total, reaped) == (6, 3)
    assert dropped == [
        "finance_report_test_preflight_222_gw0",
        "finance_report_test_mutation_333",
        "finance_report_test_planner_seq_abcd1234",
    ]

    sqls: list[str] = []
    monkeypatch.undo()

    def _fake_drop_psql(sql: str, **_kw):
        sqls.append(sql)
        return SimpleNamespace(returncode=0, stdout="DROP DATABASE\n")

    monkeypatch.setattr(rtd, "_run_psql", _fake_drop_psql)
    assert rtd.drop_database("postgres") is False
    assert rtd.drop_database("finance_report_test_bad;DROP") is False
    assert rtd.drop_database("finance_report_test_preflight_999") is True
    assert sqls == [
        'DROP DATABASE IF EXISTS "finance_report_test_preflight_999" WITH (FORCE);'
    ]

    queries: list[str] = []

    def _fake_ns_psql(sql: str, **_kw):
        queries.append(sql)
        if sql.startswith("SELECT datname"):
            return SimpleNamespace(
                returncode=0,
                stdout="finance_report_test_preflight_42\nfinance_report_test_preflight_42_gw0\n",
            )
        return SimpleNamespace(returncode=0, stdout="DROP DATABASE\n")

    monkeypatch.delenv("KEEP_TEST_DB", raising=False)
    monkeypatch.setattr(rtd, "_run_psql", _fake_ns_psql)
    assert rtd.drop_namespace_databases("preflight_42") == 2
    assert any(
        'DROP DATABASE IF EXISTS "finance_report_test_preflight_42" WITH (FORCE);' in q
        for q in queries
    )
    assert any(
        'DROP DATABASE IF EXISTS "finance_report_test_preflight_42_gw0" WITH (FORCE);'
        in q
        for q in queries
    )

    lease_file = tmp_path / "active_namespaces.json"
    live_pid = os.getpid()
    ti.register_namespace("dead_ns", lease_file, tmp_path, pid=999_999_999)
    ti.register_namespace("live_ns", lease_file, tmp_path, pid=live_pid)
    assert rtd.load_active_namespaces(lease_file) == ["live_ns"]
    ti.unregister_namespace("live_ns", lease_file, tmp_path, pid=live_pid)
    assert rtd.load_active_namespaces(lease_file) == []

    wt_backend = tmp_path / "wt_active" / "apps" / "backend"
    wt_backend.mkdir(parents=True)
    wt_hash = hashlib.sha256(str(wt_backend.resolve()).encode()).hexdigest()[:8]
    active_wt_db = f"finance_report_test_feat_open_{wt_hash}"
    gone_wt_db = "finance_report_test_feat_merged_deadbeef"
    dead_ephem_db = "finance_report_test_preflight_999999999"

    monkeypatch.setattr(
        rtd,
        "list_test_databases",
        lambda **_kw: [active_wt_db, gone_wt_db, dead_ephem_db],
    )
    monkeypatch.setattr(rtd, "list_active_databases", lambda **_kw: set())
    monkeypatch.setattr(rtd, "load_active_namespaces", lambda: [])
    monkeypatch.setattr(rtd, "active_worktree_db_names", lambda _r=None: {active_wt_db})
    monkeypatch.setattr(rtd, "is_live_ephemeral_pid", lambda _ns: False)
    ephem_dropped: list[str] = []
    monkeypatch.setattr(
        rtd, "drop_database", lambda db, **_kw: ephem_dropped.append(db) or True
    )
    reaped_e, _ = rtd.reap_orphaned_test_databases(ephemeral_only=True)
    assert reaped_e == 1 and ephem_dropped == [dead_ephem_db]
    ephem_dropped.clear()
    reaped_all, total_wt = rtd.reap_orphaned_test_databases()
    assert (total_wt, reaped_all) == (3, 2)
    assert ephem_dropped == [gone_wt_db, dead_ephem_db]

    assert ti.is_droppable_test_db("finance_report_test")
    assert ti.is_droppable_test_db("finance_report_test_gw3")
    assert ti.is_droppable_test_db(ti.get_test_db_name("feat_x_1a2b3c4d"))
    for name in ("finance_report", "postgres", "finance_report_gw0", "", None):
        assert not ti.is_droppable_test_db(name), name

    conftest_lines = (
        (ROOT / "apps/backend/tests/conftest.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    drop_calls = [
        line for line in conftest_lines if "await _drop_test_database(" in line
    ]
    assert len(drop_calls) == 1
    assert (
        "is_droppable_test_db(db_name)"
        in conftest_lines[conftest_lines.index(drop_calls[0]) - 1]
    )


def test_no_db_marker_lazy_db_and_excludes_integration() -> None:
    unreachable = "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/nope"
    env = {**os.environ, "DATABASE_URL": unreachable, "TEST_DATABASE_URL": unreachable}
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--no-cov",
            "-o",
            "addopts=",
            "-m",
            "no_db",
            "-q",
        ],
        cwd=ROOT / "apps/backend",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--no-cov",
            "-o",
            "addopts=",
            "-m",
            "no_db",
            "--collect-only",
            "-q",
        ],
        cwd=ROOT / "apps/backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + "\n" + collected.stderr
    nodeids = [
        line.strip()
        for line in collected.stdout.splitlines()
        if "::" in line and not line.startswith(("=", "-"))
    ]
    assert nodeids
    forbidden = [n for n in nodeids if n.startswith("tests/integration/")]
    assert forbidden == [], (
        f"Integration tests must not carry pytest.mark.no_db: {forbidden}"
    )


def _make_poll_client(steps: list[tuple[dict, list[dict]]]) -> httpx.AsyncClient:
    state = {"idx": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/statements/stmt-1":
            idx = min(state["idx"], len(steps) - 1)
            payload = steps[idx][0]
            if payload["status"] != "parsed":
                state["idx"] += 1
            return httpx.Response(200, json=payload)
        if request.url.path == "/api/statements/stmt-1/runs":
            idx = min(state["idx"], len(steps) - 1)
            runs = steps[idx][1]
            state["idx"] += 1
            return httpx.Response(200, json={"items": runs, "total": len(runs)})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_e2e_auto_accept_poller_waits_and_fails_fast() -> None:
    steps = [
        ({"id": "stmt-1", "status": "parsing"}, []),
        (
            {"id": "stmt-1", "status": "parsed"},
            [{"kind": "classify", "state": "requested"}],
        ),
        (
            {"id": "stmt-1", "status": "parsed"},
            [{"kind": "classify", "state": "running"}],
        ),
        ({"id": "stmt-1", "status": "approved", "transactions": [{"id": "t1"}]}, []),
    ]

    async def _run() -> tuple[dict, list[dict]]:
        async with _make_poll_client(steps) as client:
            return await wait_for_auto_approved_statement(
                client,
                api_url=lambda p: f"http://test.local/api{p}",
                statement_id="stmt-1",
                timeout_ms=5000,
                poll_seconds=0.0,
                fetch_entries=lambda _st: asyncio.sleep(
                    0, result=(True, [{"id": "je-1"}])
                ),
            )

    stmt, entries = asyncio.run(_run())
    assert stmt["status"] == "approved" and entries == [{"id": "je-1"}]

    for runs, fragment in (
        (
            [{"kind": "classify", "state": "failed", "error_code": "classify_timeout"}],
            "classify_timeout",
        ),
        ([], "classify_run=None"),
    ):

        async def _fail_parsed(cur_runs=runs) -> None:
            async with _make_poll_client(
                [
                    (
                        {"id": "stmt-1", "status": "parsed", "confidence_score": 95},
                        cur_runs,
                    )
                ]
            ) as client:
                await wait_for_auto_approved_statement(
                    client,
                    api_url=lambda p: f"http://test.local/api{p}",
                    statement_id="stmt-1",
                    timeout_ms=5000,
                    poll_seconds=0.0,
                    fetch_entries=lambda _st: asyncio.sleep(0, result=(True, [])),
                )

        with pytest.raises(Failed, match=fragment):
            asyncio.run(_fail_parsed())

    async def _fail_rejected() -> None:
        async with _make_poll_client(
            [
                (
                    {
                        "id": "stmt-1",
                        "status": "rejected",
                        "validation_error": "bad balance",
                    },
                    [],
                )
            ]
        ) as client:
            await wait_for_auto_approved_statement(
                client,
                api_url=lambda p: f"http://test.local/api{p}",
                statement_id="stmt-1",
                timeout_ms=5000,
                poll_seconds=0.0,
                fetch_entries=lambda _st: asyncio.sleep(0, result=(True, [])),
            )

    with pytest.raises(Failed, match="status=rejected"):
        asyncio.run(_fail_rejected())

    for rel in (
        "tests/e2e/test_zero_click_statement_journey.py",
        "tests/e2e/test_stage1_routing_journey.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "wait_for_auto_approved_statement" in text
        assert "status in ('parsed'" not in text


def test_version_check_pin_matches_tag_or_short_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run_vc(payload: dict, expected: str) -> None:
        class _Client:
            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

            async def get(self, _url: str) -> SimpleNamespace:
                return SimpleNamespace(status_code=200, json=lambda: payload)

        monkeypatch.setattr(
            version_check_mod.httpx, "AsyncClient", lambda **_kw: _Client()
        )
        monkeypatch.setattr(
            version_check_mod,
            "resolve_expected_commit",
            lambda _ref: VERSION_CHECK_COMMIT,
        )
        cfg = SimpleNamespace(
            APP_URL="https://report-staging.example",
            EXPECTED_VERSION=expected,
            TEST_ENV="staging",
        )
        asyncio.run(version_check_mod.test_deployed_version_matches_source(cfg))

    _run_vc({"git_sha": "v0.2.92", "version": "v0.2.92"}, "v0.2.92")
    _run_vc(
        {"git_sha": VERSION_CHECK_COMMIT[:7], "version": VERSION_CHECK_COMMIT[:7]},
        "v0.2.92",
    )
    for served in ("v0.2.91", "0000000"):
        with pytest.raises(
            AssertionError, match="does not match pinned target v0.2.92"
        ):
            _run_vc({"git_sha": served, "version": served}, "v0.2.92")

    monkeypatch.delenv("APP_VERSION_REF", raising=False)
    monkeypatch.setenv("EXPECTED_SHA", "abc1234")
    assert expected_version_from_env() is None
    monkeypatch.setenv("APP_VERSION_REF", "v0.2.94")
    assert expected_version_from_env() == "v0.2.94"


def test_pdf_corpus_oracle_offline_non_short_circuit_and_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert oracle_mod.main(["--max-workers", "0"]) == 2
    assert oracle_mod.main(["--fixture", "does_not_exist"]) == 2
    assert oracle_mod.main(["--app-url", "  "]) == 2

    report_path = tmp_path / "pdf_corpus_oracle.json"
    summary_path = tmp_path / "pdf_corpus_oracle_summary.json"
    rc = oracle_mod.main(
        [
            "--fixture",
            "bsb_001_straits_capital",
            "--json-report",
            str(report_path),
            "--output-summary",
            str(summary_path),
        ]
    )
    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert report["suite"] == "pdf_corpus_oracle" and report["mode"] == "offline"
    assert (
        report["summary"]["total"],
        report["summary"]["passed"],
        report["summary"]["failed"],
    ) == (1, 1, 0)
    assert summary["status"] == "PASS" and summary["failures_by_fixture"] == {}

    seen_specs: list[str] = []

    class _FakeClient:
        def __init__(self, **_kw: Any) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, path: str, *, json: dict[str, Any]) -> Any:
            if (
                path == "/api/auth/register"
                and "bsb_001_straits_capital" in json["display_name"]
            ):
                return SimpleNamespace(status_code=500, text="register boom")
            return SimpleNamespace(
                status_code=201, json=lambda: {"access_token": "tok"}
            )

    def _fake_verify(
        client: Any, spec: oracle_mod.CorpusStatementSpec, **_kw: Any
    ) -> dict[str, Any]:
        assert client.headers["Authorization"] == "Bearer tok"
        seen_specs.append(spec.fixture_id)
        return {
            "fixture_id": spec.fixture_id,
            "statement_id": "stmt-2",
            "delete_status": 204,
            "comparison": {"passed": True, "invariants": [], "failures": []},
        }

    with monkeypatch.context() as mp:
        mp.setattr(httpx, "Client", _FakeClient)
        mp.setattr(oracle_mod, "run_live_pdf_statement_verification", _fake_verify)
        live_report = tmp_path / "live_report.json"
        live_summary = tmp_path / "live_summary.json"
        live_rc = oracle_mod.main(
            [
                "--app-url",
                "http://127.0.0.1:8000",
                "--fixture",
                "bsb_001_straits_capital",
                "--fixture",
                "dbs_statement_fixture",
                "--max-workers",
                "1",
                "--json-report",
                str(live_report),
                "--output-summary",
                str(live_summary),
            ]
        )
    assert live_rc == 1 and seen_specs == ["dbs_statement_fixture"]
    live_rep_data = json.loads(live_report.read_text(encoding="utf-8"))
    live_sum_data = json.loads(live_summary.read_text(encoding="utf-8"))
    assert live_rep_data["results"][0]["status"] == "FAIL"
    assert live_rep_data["results"][1]["status"] == "PASS"
    assert live_sum_data["status"] == "FAIL"
    assert list(live_sum_data["failures_by_fixture"]) == ["bsb_001_straits_capital"]

    barrier = threading.Barrier(2, timeout=2.0)
    client_ids: dict[str, int] = {}
    auth_headers: dict[str, str] = {}

    class _ConcurrentClient:
        def __init__(self, **_kw: Any) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self) -> _ConcurrentClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, path: str, *, json: dict[str, Any]) -> Any:
            return SimpleNamespace(
                status_code=201,
                json=lambda: {"access_token": f"tok-{json['display_name']}"},
            )

    def _concurrent_verify(
        client: Any, spec: oracle_mod.CorpusStatementSpec, **_kw: Any
    ) -> dict[str, Any]:
        client_ids[spec.fixture_id] = id(client)
        auth_headers[spec.fixture_id] = client.headers["Authorization"]
        barrier.wait()
        return {
            "fixture_id": spec.fixture_id,
            "statement_id": f"stmt-{spec.fixture_id}",
            "delete_status": 204,
            "comparison": {"passed": True, "invariants": [], "failures": []},
        }

    with monkeypatch.context() as mp:
        mp.setattr(httpx, "Client", _ConcurrentClient)
        mp.setattr(
            oracle_mod, "run_live_pdf_statement_verification", _concurrent_verify
        )
        par_report = tmp_path / "parallel.json"
        par_rc = oracle_mod.main(
            [
                "--app-url",
                "http://127.0.0.1:8000",
                "--fixture",
                "dbs_statement_fixture",
                "--fixture",
                "bsb_001_straits_capital",
                "--max-workers",
                "2",
                "--json-report",
                str(par_report),
            ]
        )
    assert (
        par_rc == 0
        and len(set(client_ids.values())) == 2
        and len(set(auth_headers.values())) == 2
    )
    assert [
        r["fixture_id"]
        for r in json.loads(par_report.read_text(encoding="utf-8"))["results"]
    ] == [
        "bsb_001_straits_capital",
        "dbs_statement_fixture",
    ]

    manifest = oracle_mod.yaml.safe_load(
        (oracle_mod.REPO_ROOT / "runtime-hooks.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    by_id = {c["id"]: c for c in manifest["checks"]}
    tokens = shlex.split(by_id["pdf_corpus_oracle"]["argv"][2].split("&&", 1)[1])
    assert tokens[:3] == ["python", "-m", "tests.benchmarks.pdf_corpus_oracle"]
    assert tokens[tokens.index("--json-report") + 1].endswith("pdf_corpus_oracle.json")
    assert tokens[tokens.index("--output-summary") + 1].endswith(
        "pdf_corpus_oracle_summary.json"
    )


def _load_seed_fx_rates():
    settings_stub = SimpleNamespace(database_url="postgresql+asyncpg://localhost/test")
    sqla_stub = MagicMock()
    src_config_stub = MagicMock()
    src_config_stub.settings = settings_stub
    fx_stub = MagicMock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    market_data_stub = MagicMock()
    market_data_stub.FxRate = fx_stub
    module_stubs: dict[str, object] = {
        "sqlalchemy": sqla_stub,
        "sqlalchemy.ext": sqla_stub,
        "sqlalchemy.ext.asyncio": sqla_stub,
        "src": MagicMock(),
        "src.config": src_config_stub,
        "src.models": MagicMock(),
        "src.pricing": MagicMock(),
        "src.pricing.orm": MagicMock(),
        "src.pricing.orm.market_data": market_data_stub,
    }
    sys.modules.pop("common.pricing.seed_fx_rates", None)
    with patch.dict(sys.modules, module_stubs):
        from common.pricing import seed_fx_rates

    seed_fx_rates.settings = settings_stub
    sys.modules["common.pricing.seed_fx_rates"] = seed_fx_rates
    return seed_fx_rates


async def test_seed_fx_rates_urls_seeding_and_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_fx_rates = _load_seed_fx_rates()
    with patch.object(
        seed_fx_rates.settings, "database_url", "postgresql+asyncpg://localhost/test"
    ):
        assert (
            seed_fx_rates.get_database_url("local")
            == "postgresql+asyncpg://localhost/test"
        )

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://staging-host/db")
    assert (
        seed_fx_rates.get_database_url("staging")
        == "postgresql+asyncpg://staging-host/db"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://prod-host/db")
    assert (
        seed_fx_rates.get_database_url("production")
        == "postgresql+asyncpg://prod-host/db"
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for env_name in ("staging", "production"):
        with pytest.raises(SystemExit) as exc:
            seed_fx_rates.get_database_url(env_name)
        assert exc.value.code == 1

    def _make_mock_session(existing_rates=None):
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = existing_rates or []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        return mock_engine, MagicMock(return_value=mock_ctx), mock_session

    mock_engine, mock_sm, mock_session = _make_mock_session()
    with (
        patch.object(
            seed_fx_rates,
            "get_database_url",
            return_value="postgresql+asyncpg://localhost/test",
        ),
        patch(
            "common.pricing.seed_fx_rates.create_async_engine", return_value=mock_engine
        ),
        patch("common.pricing.seed_fx_rates.async_sessionmaker", return_value=mock_sm),
    ):
        await seed_fx_rates.seed_fx_rates("local")
    assert mock_session.add.call_count == 7
    mock_session.commit.assert_awaited_once()
    mock_engine.dispose.assert_awaited_once()
    out = capsys.readouterr().out
    assert (
        "USD/USD" in out
        and "Seeded 7 FX rates" in out
        and "Unrealized FX gain: 300 SGD" in out
    )

    mock_rate = MagicMock(
        base_currency="USD", quote_currency="SGD", rate=Decimal("1.28")
    )
    mock_engine2, mock_sm2, mock_session2 = _make_mock_session(
        existing_rates=[mock_rate]
    )
    monkeypatch.setattr("builtins.input", lambda _: "y")
    with (
        patch.object(
            seed_fx_rates,
            "get_database_url",
            return_value="postgresql+asyncpg://localhost/test",
        ),
        patch(
            "common.pricing.seed_fx_rates.create_async_engine",
            return_value=mock_engine2,
        ),
        patch("common.pricing.seed_fx_rates.async_sessionmaker", return_value=mock_sm2),
    ):
        await seed_fx_rates.seed_fx_rates("local")
    assert (
        mock_session2.execute.await_count == 2
        and "Deleted existing rates" in capsys.readouterr().out
    )

    mock_engine3, mock_sm3, mock_session3 = _make_mock_session(
        existing_rates=[mock_rate]
    )
    monkeypatch.setattr("builtins.input", lambda _: "n")
    with (
        patch.object(
            seed_fx_rates,
            "get_database_url",
            return_value="postgresql+asyncpg://localhost/test",
        ),
        patch(
            "common.pricing.seed_fx_rates.create_async_engine",
            return_value=mock_engine3,
        ),
        patch("common.pricing.seed_fx_rates.async_sessionmaker", return_value=mock_sm3),
    ):
        await seed_fx_rates.seed_fx_rates("local")
    mock_session3.commit.assert_not_awaited()
    assert "Aborted" in capsys.readouterr().out

    monkeypatch.setattr(
        "sys.argv", ["common.pricing.seed_fx_rates.py", "--env", "local"]
    )
    with (
        patch(
            "common.pricing.seed_fx_rates.seed_fx_rates",
            new=MagicMock(return_value=object()),
        ),
        patch("common.pricing.seed_fx_rates.asyncio.run"),
    ):
        seed_fx_rates.main()
    assert "Seeding FX rates for environment: local" in capsys.readouterr().out

    with (
        patch(
            "common.pricing.seed_fx_rates.seed_fx_rates",
            new=MagicMock(return_value=object()),
        ) as mock_seed,
        patch(
            "common.pricing.seed_fx_rates.asyncio.run",
            side_effect=RuntimeError("DB down"),
        ),
    ):
        assert seed_fx_rates.main() == 1
    mock_seed.assert_called_once_with("local")
    assert "Error seeding FX rates" in capsys.readouterr().out

    monkeypatch.setattr(
        "sys.argv", ["common.pricing.seed_fx_rates.py", "--env", "staging"]
    )
    with (
        patch(
            "common.pricing.seed_fx_rates.seed_fx_rates",
            new=MagicMock(return_value=object()),
        ) as mock_seed2,
        patch("common.pricing.seed_fx_rates.asyncio.run") as mock_run2,
    ):
        seed_fx_rates.main()
    mock_seed2.assert_called_once_with("staging")
    mock_run2.assert_called_once()


def test_pdf_fixture_generator_runs_module_from_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invoke the PDF fixture generator as a module from REPO_ROOT."""
    monkeypatch.setenv("STRICT_E2E_GATES", "1")
    monkeypatch.chdir(tmp_path)
    pdf_fixture_paths._run_generator("moomoo", "--output", str(tmp_path))
    pdfs = list((tmp_path / "moomoo").glob("test_moomoo_*.pdf"))
    assert len(pdfs) == 1
    assert pdfs[0].stat().st_size > 0
