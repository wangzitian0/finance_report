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
    assert snapshot._classify("done", deployments) == "platform-ok-check-application-or-route"


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
