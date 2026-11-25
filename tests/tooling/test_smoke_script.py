from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = ROOT_DIR / "common/runtime/shell/smoke_test.sh"


class _StubServer:
    def __init__(self, health_payload: dict[str, Any]) -> None:
        self.health_payload = health_payload
        self.requests: list[tuple[str, str]] = []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def do_OPTIONS(self) -> None:
                parent.requests.append(("OPTIONS", self.path))
                self.send_response(200)
                origin = self.headers.get("Origin", "*")
                self.send_header("Access-Control-Allow-Origin", origin)
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
                    body = b'{"detail":"Not authenticated"}'
                    self.send_response(401)
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
                _ = self.rfile.read(length)
                if self.path == "/api/auth/login":
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

    def __enter__(self) -> _StubServer:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def _head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, text=True).strip()


def _run_smoke(base_url: str, *args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SMOKE_READY_ATTEMPTS": "2",
        "SMOKE_READY_SLEEP_SECONDS": "0",
        **(env_overrides or {}),
    }
    return subprocess.run(
        ["bash", str(SMOKE_SCRIPT), base_url, *args],
        cwd=ROOT_DIR,
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


def test_smoke_script_prod_mode_is_readonly_and_passes() -> None:
    sha = _head_sha()
    with _StubServer(_healthy_payload(sha)) as srv:
        res = _run_smoke(srv.base_url, "prod", env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha})
    assert res.returncode == 0, res.stdout + res.stderr
    assert not any(method == "POST" for method, _ in srv.requests)
    assert any(path == "/api/health?full=1" for _, path in srv.requests)


def test_smoke_script_staging_mode_runs_post_and_requires_market_data() -> None:
    sha = _head_sha()
    with _StubServer(_healthy_payload(sha)) as srv:
        res = _run_smoke(srv.base_url, env_overrides={"ENVIRONMENT": "staging", "APP_VERSION_REF": sha})
    assert res.returncode == 0, res.stdout + res.stderr
    assert ("POST", "/api/auth/login") in srv.requests

    no_md = _healthy_payload(sha)
    del no_md["checks"]["market_data"]
    with _StubServer(no_md) as srv:
        failed = _run_smoke(srv.base_url, env_overrides={"ENVIRONMENT": "staging", "APP_VERSION_REF": sha})
    assert failed.returncode == 1 and "market_data" in failed.stdout


def test_smoke_script_fails_on_absent_dependency_mismatch_and_bad_mode() -> None:
    sha = _head_sha()
    bad_dep = _healthy_payload(sha)
    bad_dep["checks"]["llm"] = {"status": "absent", "required": True}
    with _StubServer(bad_dep) as srv:
        res = _run_smoke(srv.base_url, "prod", env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha})
    assert res.returncode == 1 and "llm" in res.stdout

    with _StubServer(_healthy_payload("0000000")) as srv:
        mismatch = _run_smoke(srv.base_url, "prod", env_overrides={"ENVIRONMENT": "production", "APP_VERSION_REF": sha})
    assert mismatch.returncode == 1 and "git_sha mismatch" in mismatch.stdout

    invalid_mode = _run_smoke("http://127.0.0.1:9", "invalid-mode", env_overrides={"ENVIRONMENT": "development"})
    assert invalid_mode.returncode == 2 and "Invalid MODE" in invalid_mode.stdout


@pytest.mark.parametrize("env_name", ["preview", "staging", "production"])
def test_smoke_script_requires_app_version_ref_in_deployed_envs(env_name: str) -> None:
    base_env = {k: v for k, v in os.environ.items() if k != "APP_VERSION_REF"}
    res = subprocess.run(
        ["bash", str(SMOKE_SCRIPT), "http://127.0.0.1:9"],
        cwd=ROOT_DIR,
        env=base_env | {"ENVIRONMENT": env_name},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 2 and "APP_VERSION_REF" in res.stdout
