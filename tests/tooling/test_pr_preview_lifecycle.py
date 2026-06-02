"""AC8.13.71 AC8.13.72 AC8.13.74: PR preview lifecycle contracts."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def lifecycle_module():
    return importlib.import_module("tools._lib.dev.pr_preview_lifecycle")


def test_AC8_13_71_preview_env_contains_stable_metadata() -> None:
    lifecycle = lifecycle_module()

    env = lifecycle.build_preview_env(
        pr_number=591,
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="wangzitian0/finance_report",
        internal_domain="zitian.party",
    )

    assert env["PR_PREVIEW_PR_NUMBER"] == "591"
    assert env["PR_PREVIEW_COMPOSE_NAME"] == "pr-591"
    assert env["PR_PREVIEW_COMPOSE_PROJECT"] == "finance_report_pr_591"
    assert env["COMPOSE_PROJECT_NAME"] == "finance_report_pr_591"
    assert env["PR_PREVIEW_CREATED_BY"] == "github-actions"
    assert env["IMAGE_TAG"] == "pr-591"
    assert env["GIT_COMMIT_SHA"] == "abc123"
    assert env["ENV_SUFFIX"] == "-pr-591"
    assert env["COMPOSE_PROFILES"] == "infra,app"


def test_AC8_13_72_allowlisted_env_diff_hides_secret_values() -> None:
    lifecycle = lifecycle_module()

    expected = {
        "IMAGE_TAG": "pr-591",
        "GIT_COMMIT_SHA": "abc123",
        "IAC_CONFIG_HASH": "deploy-abc123-1",
        "ENV_SUFFIX": "-pr-591",
        "COMPOSE_PROFILES": "infra,app",
    }
    actual_env = "\n".join(
        [
            "IMAGE_TAG=old",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=deploy-abc123-1",
            "ENV_SUFFIX=-pr-591",
            "COMPOSE_PROFILES=infra,app",
            "VAULT_APP_TOKEN=hvs.secret",
            "refreshToken=refresh-secret",
            "DATABASE_URL=postgres://secret",
        ]
    )

    diff = lifecycle.render_allowlisted_env_diff(expected, actual_env)

    assert "IMAGE_TAG: expected=pr-591 actual=old" in diff
    assert "GIT_COMMIT_SHA: match" in diff
    assert "hvs.secret" not in diff
    assert "refresh-secret" not in diff
    assert "postgres://secret" not in diff
    assert "DATABASE_URL" not in diff


def test_AC8_13_71_cleanup_preview_resources_uses_exact_pr_metadata() -> None:
    lifecycle = lifecycle_module()

    script = lifecycle.build_preview_cleanup_script(
        pr_number=591,
        compose_project="finance_report_pr_591",
        dry_run=True,
    )

    assert "finance-report-(backend|frontend|db|minio)-pr-591" in script
    assert "finance_report_pr_591_" in script
    assert "docker volume prune" not in script
    assert "docker system prune" not in script
    assert "docker builder prune" not in script
    assert "journalctl" not in script


def test_AC8_13_71_cleanup_action_deletes_compose_and_volumes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []
    ssh_payloads: list[str | None] = []

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        ssh_payloads.append(input_text)
        if "environment.one" in " ".join(cmd):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    args = SimpleNamespace(
        action="cleanup",
        pr_number=591,
        compose_name="pr-591",
        compose_id="",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="secret-key",
        github_integration_id="ghid",
        branch="feature",
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        internal_domain="zitian.party",
        host="cloud.zitian.party",
        user="root",
        ssh_key="/tmp/key",
        dry_run=True,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "environment.one" in rendered_calls
    assert "compose.delete" in rendered_calls
    assert "compose.stop" not in rendered_calls
    assert any(payload and "finance_report_pr_591_" in payload for payload in ssh_payloads)
    out = capsys.readouterr().out
    assert "Raw Dokploy response" not in out
    assert "secret-key" not in out


def test_AC8_13_72_deploy_action_reads_effective_env_before_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "ENV_SUFFIX=-pr-591",
            "COMPOSE_PROFILES=infra,app",
            "VAULT_APP_TOKEN=hvs.secret",
        ]
    )

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        rendered = " ".join(cmd)
        if "environment.one" in rendered:
            return subprocess.CompletedProcess(cmd, 0, stdout='{"compose":[]}', stderr="")
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(cmd, 0, stdout='{"composeId":"cmp-591"}', stderr="")
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"env": effective_env}),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    args = SimpleNamespace(
        action="deploy",
        pr_number=591,
        compose_name="pr-591",
        compose_id="",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="secret-key",
        github_integration_id="ghid",
        branch="feature",
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        internal_domain="zitian.party",
        host="cloud.zitian.party",
        user="root",
        ssh_key="/tmp/key",
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.update" in rendered_calls
    assert "compose.one" in rendered_calls
    assert "compose.deploy" in rendered_calls
    assert "secret-key" not in rendered_calls
    assert "VAULT_APP_TOKEN" not in rendered_calls
    assert "MINIO_ROOT_PASSWORD" not in rendered_calls


def test_AC8_13_74_scheduled_cleanup_only_reconciles_closed_prs() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert "tools/pr_preview_lifecycle.py" in workflow
    assert "--action reconcile" in workflow
    assert "tools/cleanup_pr_preview_resources.py" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journalctl" not in workflow


def test_AC8_13_71_pr_test_workflow_uses_lifecycle_for_delete() -> None:
    workflow = (ROOT / ".github/workflows/pr-test.yml").read_text()

    assert "--action delete" in workflow
    assert "compose.stop" not in workflow


def test_AC8_13_71_close_cleanup_checks_out_lifecycle_tool() -> None:
    workflow = (ROOT / ".github/workflows/pr-test.yml").read_text()

    cleanup_block = workflow.split("  cleanup:", 1)[1]
    assert "uses: actions/checkout@v4" in cleanup_block
    assert cleanup_block.index("uses: actions/checkout@v4") < cleanup_block.index(
        "python tools/pr_preview_lifecycle.py"
    )
