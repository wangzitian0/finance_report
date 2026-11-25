"""Tests for common.testing.quality_board (#3215 Slice 2C)."""

from __future__ import annotations

import http.server
import io
import json
import sys
import threading
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from infra2_sdk.manifests import load_hooks_manifest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.testing import quality_board as qb

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _FakeResp:
    def __init__(
        self, payload: bytes, *, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._payload

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_a: object) -> bool:
        return False


def test_expected_scheduled_audit_checks_matches_sdk_manifest() -> None:
    manifest_path = ROOT / "runtime-hooks.manifest.json"
    sdk_ids = [
        c.id for c in load_hooks_manifest(manifest_path).checks_for_cell("scheduled_audit")
    ]
    assert list(qb.expected_scheduled_audit_checks(manifest_path)) == sdk_ids


def test_freshness_state_machine_prevents_green_while_empty_or_stale() -> None:
    healthy_pair = {
        "staging": {"reachable": True, "status": "healthy"},
        "production": {"reachable": True, "status": "healthy"},
    }
    fresh = qb.compute_freshness(
        now=NOW,
        ci_post={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=2)),
        },
        scheduled_audit={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=4)),
            "completeness": {"completed": 4, "expected": 4},
            "latest": {"status": "pass"},
        },
        runtime_health=healthy_pair,
    )
    assert fresh["status"] == "FRESH"
    assert fresh["reasons"] == []

    # Partial completeness -> STALE_WARN
    partial = qb.compute_freshness(
        now=NOW,
        ci_post={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=2)),
        },
        scheduled_audit={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=4)),
            "completeness": {"completed": 2, "expected": 4},
            "latest": {"status": "pass"},
        },
        runtime_health=healthy_pair,
    )
    assert partial["status"] == "STALE_WARN"

    # Empty scheduled_audit -> STALE_CRITICAL (never green while empty)
    empty_audit = qb.compute_freshness(
        now=NOW,
        ci_post={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=1)),
        },
        scheduled_audit={
            "artifacts_count": 0,
            "latest_at_utc": None,
            "completeness": {"completed": 0, "expected": 4},
            "latest": None,
        },
        runtime_health=healthy_pair,
    )
    assert empty_audit["status"] == "STALE_CRITICAL"

    # Over 72h nightly age -> STALE_CRITICAL
    too_old_audit = qb.compute_freshness(
        now=NOW,
        ci_post={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=1)),
        },
        scheduled_audit={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=73)),
            "completeness": {"completed": 4, "expected": 4},
            "latest": {"status": "pass"},
        },
        runtime_health=healthy_pair,
    )
    assert too_old_audit["status"] == "STALE_CRITICAL"

    # Both runtime probes unreachable -> STALE_CRITICAL
    both_down = qb.compute_freshness(
        now=NOW,
        ci_post={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=1)),
        },
        scheduled_audit={
            "artifacts_count": 1,
            "latest_at_utc": qb.format_utc(NOW - timedelta(hours=1)),
            "completeness": {"completed": 4, "expected": 4},
            "latest": {"status": "pass"},
        },
        runtime_health={
            "staging": {"reachable": False, "status": "error"},
            "production": {"reachable": False, "status": "error"},
        },
    )
    assert both_down["status"] == "STALE_CRITICAL"


def test_artifact_download_strips_authorization_on_redirect() -> None:
    seen_headers: list[tuple[str, str | None]] = []
    zip_payload = _zip_bytes({"hello.json": b'{"ok": true}'})

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen_headers.append((self.path, self.headers.get("Authorization")))
            if self.path == "/artifact.zip":
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{self.server.server_port}/signed.zip",
                )
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(zip_payload)))
            self.end_headers()
            self.wfile.write(zip_payload)

        def log_message(self, *_args: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        files = qb.download_artifact_files(
            f"http://127.0.0.1:{server.server_port}/artifact.zip",
            token="ghp_secret_token",
        )
    finally:
        server.shutdown()
        server.server_close()

    assert files == {"hello.json": b'{"ok": true}'}
    assert seen_headers == [
        ("/artifact.zip", "Bearer ghp_secret_token"),
        ("/signed.zip", None),
    ]


def test_write_dashboard_aggregates_sources_and_escapes_html(tmp_path: Path) -> None:
    ci_zip = _zip_bytes(
        {
            "ci-post-telemetry.json": json.dumps(
                {
                    "run_id": "101",
                    "run_url": "https://github.com/o/f/actions/runs/101",
                    "sha": "1234567890",
                    "ref": "refs/heads/main",
                    "generated_at_utc": qb.format_utc(NOW - timedelta(hours=1)),
                    "timing": {
                        "execution_seconds": 210,
                        "budget": {"budget_seconds": 480, "state": "within"},
                    },
                    "coverage": {
                        "backend": {"percent_covered": 96.8},
                        "frontend": {"lines_pct": 98.4},
                    },
                    "jobs": {"lint": "success"},
                }
            ).encode("utf-8")
        }
    )
    audit_zip = _zip_bytes(
        {
            "scheduled-audit-result.json": json.dumps(
                {
                    "scheduled_audit_results": [
                        {
                            "service": "finance_report/app",
                            "version_ref": "v0.2.98",
                            "status": "pass",
                            "summary": "all 4 passed",
                            "duration_seconds": 320.0,
                            "checks": [
                                {"name": "audit_replay", "ok": True, "seconds": 80},
                                {"name": "core_journey", "ok": True, "seconds": 90},
                                {"name": "pdf_corpus_oracle", "ok": True, "seconds": 75},
                                {
                                    "name": "financial_scenario_benchmark",
                                    "ok": True,
                                    "seconds": 75,
                                },
                            ],
                            "oracle_summaries": {
                                "pdf_corpus_oracle_summary": {"passed": 8, "failed": 0}
                            },
                        }
                    ]
                }
            ).encode("utf-8")
        }
    )
    stage_zip = _zip_bytes(
        {
            "stage.json": json.dumps(
                {"env": "staging.provider_regression", "verdict": "pass"}
            ).encode("utf-8")
        }
    )

    def fake_opener(request: Any, _timeout: float) -> _FakeResp:
        url = request.full_url
        if "name=ci-post-telemetry" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 11,
                                "expired": False,
                                "created_at": qb.format_utc(NOW - timedelta(hours=1)),
                                "archive_download_url": "https://api.github.com/ci.zip",
                                "workflow_run": {"id": 101, "head_branch": "main"},
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if url == "https://api.github.com/ci.zip":
            return _FakeResp(ci_zip)
        if "workflows/ci.yml/runs" in url:
            return _FakeResp(b'{"workflow_runs": []}')
        if "name=scheduled-audit-results" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 22,
                                "expired": False,
                                "created_at": qb.format_utc(NOW - timedelta(hours=2)),
                                "archive_download_url": "https://api.github.com/audit.zip",
                                "workflow_run": {"id": 202},
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if url == "https://api.github.com/audit.zip":
            return _FakeResp(audit_zip)
        if "/actions/runs/202/artifacts" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 23,
                                "name": "stage-staging.provider_regression-post-sha-abc",
                                "expired": False,
                                "archive_download_url": "https://api.github.com/stage.zip",
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        if url == "https://api.github.com/stage.zip":
            return _FakeResp(stage_zip)
        if "reconcile-iac-inputs.yml/runs" in url:
            return _FakeResp(b'{"workflow_runs": []}')
        if "report-staging" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "status": "healthy",
                        "version": "<script>alert(1)</script>",
                        "checks": {
                            "database": {"status": "present", "detail": "ok", "duration_ms": 5}
                        },
                    }
                ).encode("utf-8")
            )
        if "report.zitian" in url:
            return _FakeResp(
                json.dumps(
                    {
                        "status": "healthy",
                        "version": "v0.2.95",
                        "checks": {
                            "market_data": {"status": "present", "detail": "ok", "duration_ms": 9}
                        },
                    }
                ).encode("utf-8")
            )
        raise AssertionError(f"unexpected URL in fake_opener: {url}")

    out_dir = tmp_path / "board"
    data = qb.write_dashboard(output_dir=out_dir, repo_root=ROOT, opener=fake_opener, now=NOW)
    assert data["freshness"]["status"] == "FRESH"
    assert data["freshness"]["completeness"] == {"completed": 4, "expected": 4}
    assert data["user_cases"]["total"] == 47
    assert data["scheduled_audit"]["runs"][0]["stage_record_verdict"] == "pass"

    html_text = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "Freshness Heartbeat: FRESH" in html_text
    assert "2026-11-25 20:00:00 UTC+8" in html_text
    assert "2026-11-25T12:00:00Z" in html_text
    assert "Nightly Completeness: <strong>4/4</strong>" in html_text
    assert "<script>alert(1)</script>" not in html_text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
