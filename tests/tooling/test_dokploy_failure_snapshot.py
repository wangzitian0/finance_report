"""Unit tests for the Dokploy platform-failure snapshot (issue #768)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = ROOT / "tools" / "dokploy_failure_snapshot.py"
_spec = importlib.util.spec_from_file_location("dokploy_failure_snapshot", _MODULE_PATH)
assert _spec and _spec.loader
snapshot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(snapshot)


def test_classify_compose_error_is_deployment_error() -> None:
    assert snapshot._classify("error", [{"status": "error", "startedAt": "1"}]) == (
        "dokploy-deployment-error"
    )


def test_classify_no_deployments_is_worker_record_domain() -> None:
    assert snapshot._classify("idle", []) == "dokploy-worker-or-deployment-record"


def test_classify_done_is_platform_ok() -> None:
    deployments = [{"status": "done", "startedAt": "2"}]
    assert (
        snapshot._classify("done", deployments)
        == "platform-ok-check-application-or-route"
    )


def test_classify_picks_latest_deployment_by_started_at() -> None:
    deployments = [
        {"status": "done", "startedAt": "2026-01-01T00:00:00Z"},
        {"status": "error", "startedAt": "2026-01-02T00:00:00Z"},
    ]
    assert snapshot._classify("done", deployments) == "dokploy-deployment-error"


def test_main_skips_cleanly_without_inputs(capsys) -> None:
    rc = snapshot.main(["--compose-id", "", "--api-url", "", "--api-key", ""])
    assert rc == 0
    assert "snapshot-skipped-missing-inputs" in capsys.readouterr().out


def test_render_markdown_includes_failure_domain() -> None:
    md = snapshot.render_markdown(
        {"compose_id": "abc", "platform_failure_domain": "dokploy-deployment-error"}
    )
    assert "platform_failure_domain" in md
    assert "dokploy-deployment-error" in md


def test_AC10_9_5_snapshot_includes_platform_health_and_signoz_links() -> None:
    """AC10.9.5: deploy failure snapshots carry platform health and SigNoz pivots."""
    links = snapshot.build_signoz_query_links(
        signoz_url="https://signoz.zitian.party",
        service_name="finance-report-backend",
        deployment_environment="staging",
        service_version="v0.1.3",
        github_run_id="12345",
    )
    platform_health = snapshot.load_platform_health(
        '{"target_container_status":"restarting",'
        '"target_container_restart_count":7,'
        '"host_load_1m":25.5,'
        '"host_memory_used_pct":91.2,'
        '"vault_agent_error_loop":true,'
        '"secret_should_not_pass":"x"}'
    )

    snap = snapshot.build_snapshot(
        "https://api",
        "k",
        "cid",
        platform_health=platform_health,
        signoz_links=links,
    )

    assert snap["target_container_status"] == "restarting"
    assert snap["target_container_restart_count"] == 7
    assert snap["host_load_1m"] == 25.5
    assert snap["vault_agent_error_loop"] is True
    assert "secret_should_not_pass" not in snap
    assert "deployment.environment=staging" in snap["signoz_logs_query_url"]
    assert "github.run_id=12345" in snap["signoz_traces_query_url"]


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_api_get_parses_json(monkeypatch) -> None:
    import json as _json

    captured: dict = {}

    def fake_urlopen(req, timeout=0):  # noqa: ANN001
        captured["headers"] = req.headers
        return _FakeResponse(_json.dumps({"composeStatus": "done"}).encode())

    monkeypatch.setattr(snapshot.urllib.request, "urlopen", fake_urlopen)
    data = snapshot._api_get("https://api/", "k", "compose.one?composeId=x")
    assert data["composeStatus"] == "done"
    # Non-default User-Agent must be set to avoid Cloudflare bot blocking.
    assert any("User-agent" in h or "User-Agent" in h for h in captured["headers"])


def test_build_snapshot_success(monkeypatch) -> None:
    monkeypatch.setattr(
        snapshot,
        "_api_get",
        lambda *a, **k: {
            "composeStatus": "done",
            "deployments": [
                {"status": "done", "startedAt": "2026-01-02T00:00:00Z", "title": "t"},
                {"status": "error", "startedAt": "2026-01-01T00:00:00Z"},
            ],
        },
    )
    snap = snapshot.build_snapshot("https://api", "k", "cid")
    assert snap["compose_status"] == "done"
    assert snap["deployment_count"] == 2
    assert snap["latest_deployment_status"] == "done"
    assert snap["platform_failure_domain"] == "platform-ok-check-application-or-route"


def test_build_snapshot_api_unreachable(monkeypatch) -> None:
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise snapshot.urllib.error.URLError("down")

    monkeypatch.setattr(snapshot, "_api_get", boom)
    snap = snapshot.build_snapshot("https://api", "k", "cid")
    assert snap["platform_failure_domain"] == "dokploy-api-unreachable"
    assert "could not read" in snap["error"]


def test_main_happy_path_prints_snapshot(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        snapshot,
        "build_snapshot",
        lambda *a, **k: {
            "compose_id": "cid",
            "platform_failure_domain": "dokploy-deployment-error",
        },
    )
    rc = snapshot.main(
        [
            "--compose-id",
            "cid",
            "--api-url",
            "https://api",
            "--api-key",
            "k",
            "--markdown",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "dokploy-deployment-error" in out


def test_AC10_9_5_main_missing_inputs_still_prints_signoz_links(capsys) -> None:
    """AC10.9.5: missing Dokploy inputs do not suppress run-to-SigNoz pivots."""
    rc = snapshot.main(
        [
            "--compose-id",
            "",
            "--api-url",
            "",
            "--api-key",
            "",
            "--signoz-url",
            "https://signoz.zitian.party",
            "--deployment-environment",
            "production",
            "--service-version",
            "v0.1.3",
            "--github-run-id",
            "456",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "snapshot-skipped-missing-inputs" in out
    assert "signoz_logs_query_url" in out
    assert "github.run_id=456" in out


def test_AC10_9_5_main_does_not_emit_empty_github_run_filter(capsys) -> None:
    """AC10.9.5: SigNoz pivots require a concrete GitHub run id."""
    rc = snapshot.main(
        [
            "--compose-id",
            "",
            "--api-url",
            "",
            "--api-key",
            "",
            "--signoz-url",
            "https://signoz.zitian.party",
            "--deployment-environment",
            "production",
            "--service-version",
            "v0.1.3",
            "--github-run-id",
            "",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "snapshot-skipped-missing-inputs" in out
    assert "signoz_logs_query_url" not in out
    assert "github.run_id=" not in out


def test_build_snapshot_no_deployments(monkeypatch) -> None:
    monkeypatch.setattr(
        snapshot,
        "_api_get",
        lambda *a, **k: {"composeStatus": "idle", "deployments": []},
    )
    snap = snapshot.build_snapshot("https://api", "k", "cid")
    assert snap["deployment_count"] == 0
    assert snap["latest_deployment_status"] == "none"
    assert snap["platform_failure_domain"] == "dokploy-worker-or-deployment-record"
