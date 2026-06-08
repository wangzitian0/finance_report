"""AC8.13.71 AC8.13.72 AC8.13.74: PR preview lifecycle contracts."""

from __future__ import annotations

import importlib
import inspect
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
    assert env["IMAGE_TAG"] == "pr-591-abc123"
    assert env["GIT_COMMIT_SHA"] == "abc123"
    assert env["ENV_SUFFIX"] == "-pr-591-abc123"
    assert env["ENV_DOMAIN_SUFFIX"] == "-pr-591-abc123"
    assert env["NETWORK_SUFFIX"] == "-pr-591"
    assert env["NEXT_PUBLIC_API_URL"] == "https://report-pr-591-abc123.zitian.party"
    assert env["NEXT_PUBLIC_APP_URL"] == "https://report-pr-591-abc123.zitian.party"
    assert env["DB_HOST"] == "finance-report-db-pr-591-abc123"
    assert env["S3_HOST"] == "finance-report-minio-pr-591-abc123"
    assert env["S3_ENDPOINT"] == "http://finance-report-minio-pr-591-abc123:9000"
    assert env["COMPOSE_PROFILES"] == "infra,app"


def test_AC8_13_101_preview_app_url_is_commit_scoped() -> None:
    """AC8.13.101: PR preview readiness targets a commit-scoped route."""
    lifecycle = lifecycle_module()

    assert lifecycle.preview_commit_slug("ABC123xyz456789") == "abc123xyz456"
    assert (
        lifecycle.preview_app_url(591, "ABC123xyz456789", "zitian.party")
        == "https://report-pr-591-abc123xyz456.zitian.party"
    )
    assert lifecycle.preview_port_offset(
        591, "abc123"
    ) != lifecycle.preview_port_offset(591, "def456")
    assert lifecycle.preview_compose_command(591) == (
        "compose -p finance_report_pr_591 -f docker-compose.pr-preview.yml "
        "up -d --pull always --no-build --remove-orphans"
    )


def test_AC8_13_102_preview_network_is_pr_scoped_to_limit_subnet_usage() -> None:
    """AC8.13.102: PR previews do not allocate one Docker network per commit."""
    compose = (ROOT / "docker-compose.pr-preview.yml").read_text()
    network_block = compose.split("networks:", 1)[1]

    assert "name: finance-report-internal${NETWORK_SUFFIX:-}" in network_block
    assert "name: finance-report-internal${ENV_SUFFIX:-}" not in network_block


def test_AC8_13_71_root_compose_passes_git_sha_to_backend_runtime_and_frontend_build() -> (
    None
):
    compose = (ROOT / "docker-compose.yml").read_text()
    backend_block = compose.split("  backend:", 1)[1].split("  frontend:", 1)[0]
    frontend_block = compose.split("  frontend:", 1)[1].split("networks:", 1)[0]

    assert "GIT_COMMIT_SHA: ${GIT_COMMIT_SHA:-unknown}" in backend_block
    assert backend_block.index("environment:") < backend_block.index(
        "GIT_COMMIT_SHA: ${GIT_COMMIT_SHA:-unknown}"
    )
    assert "GIT_COMMIT_SHA: ${GIT_COMMIT_SHA:-}" in frontend_block
    assert frontend_block.index("args:") < frontend_block.index(
        "GIT_COMMIT_SHA: ${GIT_COMMIT_SHA:-}"
    )


def test_AC8_13_71_dash_prefixed_environment_id_is_accepted() -> None:
    lifecycle = lifecycle_module()

    argv = lifecycle.normalize_dash_prefixed_values(
        ["--action", "deploy", "--environment-id", "-fzh5EGJN74I1AjNEpVUr"]
    )

    assert "--environment-id=-fzh5EGJN74I1AjNEpVUr" in argv
    assert "-fzh5EGJN74I1AjNEpVUr" not in argv


def test_AC8_13_71_env_parser_ignores_comments_and_blank_lines() -> None:
    lifecycle = lifecycle_module()

    parsed = lifecycle.parse_env(
        "\n# comment\n IMAGE_TAG = pr-591 \ninvalid-line\nGIT_COMMIT_SHA=abc123\n"
    )

    assert parsed == {"IMAGE_TAG": " pr-591 ", "GIT_COMMIT_SHA": "abc123"}


def test_AC8_13_72_allowlisted_env_diff_hides_secret_values() -> None:
    lifecycle = lifecycle_module()

    expected = {
        "IMAGE_TAG": "pr-591-abc123",
        "GIT_COMMIT_SHA": "abc123",
        "IAC_CONFIG_HASH": "deploy-abc123-1",
        "COMPOSE_PROJECT_NAME": "finance_report_pr_591",
        "ENV_SUFFIX": "-pr-591-abc123",
        "ENV_DOMAIN_SUFFIX": "-pr-591-abc123",
        "NETWORK_SUFFIX": "-pr-591",
        "NEXT_PUBLIC_API_URL": "https://report-pr-591-abc123.zitian.party",
        "DB_HOST": "finance-report-db-pr-591-abc123",
        "S3_HOST": "finance-report-minio-pr-591-abc123",
        "COMPOSE_PROFILES": "infra,app",
    }
    actual_env = "\n".join(
        [
            "IMAGE_TAG=old",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=deploy-abc123-1",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
            "VAULT_APP_TOKEN=hvs.secret",
            "refreshToken=refresh-secret",
            "DATABASE_URL=postgres://secret",
        ]
    )

    diff = lifecycle.render_allowlisted_env_diff(expected, actual_env)

    assert "IMAGE_TAG: expected=pr-591-abc123 actual=old" in diff
    assert "GIT_COMMIT_SHA: match" in diff
    assert "hvs.secret" not in diff
    assert "refresh-secret" not in diff
    assert "postgres://secret" not in diff
    assert "DATABASE_URL" not in diff


def test_AC8_13_101_compose_summary_hides_raw_env() -> None:
    """AC8.13.101: Dokploy diagnostics print deploy state without raw env."""
    lifecycle = lifecycle_module()

    summary = lifecycle.render_compose_summary(
        {
            "composeId": "cmp-591",
            "name": "pr-591",
            "sourceType": "github",
            "repository": "finance_report",
            "branch": "feature",
            "composePath": "docker-compose.pr-preview.yml",
            "composeStatus": "running",
            "command": "compose -p finance_report_pr_591 -f docker-compose.pr-preview.yml up -d --pull always --no-build --remove-orphans",
            "deployments": [
                {
                    "deploymentId": "dep-591",
                    "status": "running",
                    "createdAt": "2026-06-06T07:42:00Z",
                    "error": "image pull failed token=secret-refresh hvs.secret",
                    "errorMessage": "network creation failed",
                    "logPath": "/etc/dokploy/logs/compose-pr-591.log",
                }
            ],
            "env": "DATABASE_URL=postgres://secret\nrefreshToken=secret",
        },
        label="after-deploy-trigger",
    )

    assert "Dokploy compose summary (after-deploy-trigger)" in summary
    assert "composeId: cmp-591" in summary
    assert "branch: feature" in summary
    assert "composeStatus: running" in summary
    assert "deployment_count: 1" in summary
    assert "latest_deployment_deploymentId: dep-591" in summary
    assert "latest_deployment_error: image pull failed token=<redacted>" in summary
    assert "latest_deployment_errorMessage: network creation failed" in summary
    assert "latest_deployment_logPath: /etc/dokploy/logs/compose-pr-591.log" in summary
    assert "env_present: True" in summary
    assert "raw_compose_printed: false" in summary
    assert "raw_deployment_printed: false" in summary
    assert "postgres://secret" not in summary
    assert "refreshToken" not in summary
    assert "DATABASE_URL" not in summary
    assert "secret-refresh" not in summary
    assert "hvs.secret" not in summary


def test_AC8_13_101_compose_summary_sorts_latest_deployment() -> None:
    """AC8.13.101: Dokploy diagnostics do not trust API deployment ordering."""
    lifecycle = lifecycle_module()

    summary = lifecycle.render_compose_summary(
        {
            "composeId": "cmp-591",
            "composeStatus": "running",
            "deployments": [
                {
                    "deploymentId": "old",
                    "status": "done",
                    "createdAt": "2026-06-06T08:14:05.241Z",
                },
                {
                    "deploymentId": "new",
                    "status": "running",
                    "createdAt": "2026-06-06T11:18:03.000Z",
                },
            ],
        },
        label="after-deploy-trigger",
    )

    assert "latest_deployment_deploymentId: new" in summary
    assert "latest_deployment_status: running" in summary


def test_AC8_13_102_dokploy_deploy_waits_for_worker_done_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Readiness starts only after Dokploy finishes the deploy."""
    lifecycle = lifecycle_module()
    states = iter(
        [
            {"composeId": "cmp-591", "composeStatus": "idle", "deployments": []},
            {
                "composeId": "cmp-591",
                "composeStatus": "running",
                "deployments": [{"deploymentId": "dep-591", "status": "running"}],
            },
            {
                "composeId": "cmp-591",
                "composeStatus": "done",
                "deployments": [{"deploymentId": "dep-591", "status": "done"}],
            },
        ]
    )

    monkeypatch.setattr(
        lifecycle, "get_compose_data", lambda *args, **kwargs: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)

    lifecycle.wait_for_dokploy_deployment_rollout(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        compose_id="cmp-591",
        previous_deployment_ids={"old-dep"},
        timeout_seconds=30,
    )

    out = capsys.readouterr().out
    assert "deployment-rollout-attempt-1" in out
    assert "Dokploy rollout probe: attempt=1" in out
    assert "Dokploy rollout probe: attempt=2" in out
    assert "Dokploy rollout probe: attempt=3" in out
    assert "Dokploy deployment observed: compose_id=cmp-591" in out
    assert "new_deployment_ids=dep-591" in out
    assert "latest_deployment_status=running" in out
    assert "latest_deployment_status=done" in out


def test_AC8_13_102_dokploy_rollout_record_window_allows_worker_queue() -> None:
    """AC8.13.102: The deployment-record gate is fast, but not shorter than Dokploy queue lag."""
    lifecycle = lifecycle_module()

    signature = inspect.signature(lifecycle.wait_for_dokploy_deployment_rollout)

    assert signature.parameters["timeout_seconds"].default == 900
    assert signature.parameters["new_deployment_timeout_seconds"].default == 600


def test_AC8_13_102_late_rollout_record_gets_completion_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: A late Dokploy record still gets time to reach done."""
    lifecycle = lifecycle_module()
    states = iter(
        [
            {"composeId": "cmp-591", "composeStatus": "idle", "deployments": []},
            {
                "composeId": "cmp-591",
                "composeStatus": "running",
                "deployments": [{"deploymentId": "dep-591", "status": "running"}],
            },
            {
                "composeId": "cmp-591",
                "composeStatus": "running",
                "deployments": [{"deploymentId": "dep-591", "status": "running"}],
            },
            {
                "composeId": "cmp-591",
                "composeStatus": "done",
                "deployments": [{"deploymentId": "dep-591", "status": "done"}],
            },
        ]
    )
    times = iter([0.0, 590.0, 610.0, 620.0, 630.0])

    monkeypatch.setattr(
        lifecycle, "get_compose_data", lambda *args, **kwargs: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)

    lifecycle.wait_for_dokploy_deployment_rollout(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        compose_id="cmp-591",
        previous_deployment_ids={"old-dep"},
    )


def test_AC8_13_102_dokploy_rollout_timeout_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle,
        "get_compose_data",
        lambda *args, **kwargs: {
            "composeId": "cmp-591",
            "composeStatus": "idle",
            "deployments": [],
        },
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)
    times = iter([0.0, 2.0])
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(times))

    with pytest.raises(
        lifecycle.DokployDeploymentDidNotStart,
        match="did not create a new deployment before readiness",
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            compose_id="cmp-591",
            timeout_seconds=1,
        )


def test_AC8_13_102_dokploy_rollout_error_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle,
        "get_compose_data",
        lambda *args, **kwargs: {
            "composeId": "cmp-591",
            "composeStatus": "running",
            "deployments": [{"deploymentId": "dep-591", "status": "error"}],
        },
    )

    with pytest.raises(RuntimeError, match="deployment failed before readiness"):
        lifecycle.wait_for_dokploy_deployment_rollout(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            compose_id="cmp-591",
            previous_deployment_ids={"old-dep"},
        )


def test_AC8_13_102_done_compose_without_new_record_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Done composes with old records fail before app readiness."""
    lifecycle = lifecycle_module()
    states = iter(
        [
            {
                "composeStatus": "done",
                "deployments": [{"deploymentId": "old-dep"}],
            }
        ]
    )

    monkeypatch.setattr(
        lifecycle, "get_compose_data", lambda *args, **kwargs: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)

    with pytest.raises(
        lifecycle.DokployDeploymentDidNotStart,
        match="did not create a new deployment record for this rollout",
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            lifecycle.DokployConfig(
                api_url="https://cloud.example/api",
                api_key="secret",
            ),
            compose_id="cmp-1",
            previous_deployment_ids={"old-dep"},
            timeout_seconds=1,
            new_deployment_timeout_seconds=0,
        )

    out = capsys.readouterr().out
    assert "proceeding to commit-scoped readiness" not in out
    assert "platform_failure_domain=dokploy-worker-or-deployment-record" in out


def test_AC8_13_102_rollout_poll_retries_transient_dokploy_api_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Transient Dokploy control-plane polling failures stay inside rollout retry."""
    lifecycle = lifecycle_module()
    calls = 0

    def fake_get_compose_data(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Dokploy request failed for compose.one?api_key=secret")
        return {
            "composeStatus": "done",
            "deployments": [{"deploymentId": "new-dep", "status": "done"}],
        }

    monkeypatch.setattr(lifecycle, "get_compose_data", fake_get_compose_data)
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)

    lifecycle.wait_for_dokploy_deployment_rollout(
        lifecycle.DokployConfig(api_url="https://cloud.example/api", api_key="secret"),
        compose_id="cmp-1",
        previous_deployment_ids=set(),
        timeout_seconds=10,
    )

    out = capsys.readouterr().out
    assert calls == 2
    assert "Dokploy rollout probe API failure" in out
    assert "api_key=secret" not in out


def test_AC8_13_102_compose_error_logs_redacted_deployment_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle,
        "get_compose_data",
        lambda *args, **kwargs: {
            "composeId": "cmp-591",
            "composeStatus": "error",
            "deployments": [
                {
                    "deploymentId": "dep-591",
                    "status": "error",
                    "error": (
                        "docker compose failed: pull access denied "
                        "AUTHORIZATION=Bearer secret-token hvs.secret"
                    ),
                }
            ],
        },
    )

    with pytest.raises(
        RuntimeError,
        match="compose entered error status before readiness polling",
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            compose_id="cmp-591",
            previous_deployment_ids={"old-dep"},
        )

    out = capsys.readouterr().out
    assert "compose-error-attempt-1" in out
    assert "latest_deployment_deploymentId: dep-591" in out
    assert "latest_deployment_error: docker compose failed: pull access denied" in out
    assert "AUTHORIZATION=<redacted>" in out
    assert "raw_deployment_printed: false" in out
    assert "secret-token" not in out
    assert "hvs.secret" not in out


def test_AC8_13_102_stale_compose_error_waits_for_new_rollout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()
    states = iter(
        [
            {
                "composeId": "cmp-591",
                "composeStatus": "error",
                "deployments": [
                    {
                        "deploymentId": "old-dep",
                        "status": "error",
                        "description": "Commit: old-sha",
                    }
                ],
            },
            {
                "composeId": "cmp-591",
                "composeStatus": "done",
                "deployments": [
                    {"deploymentId": "old-dep", "status": "error"},
                    {"deploymentId": "dep-592", "status": "done"},
                ],
            },
        ]
    )

    monkeypatch.setattr(
        lifecycle, "get_compose_data", lambda *args, **kwargs: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)

    lifecycle.wait_for_dokploy_deployment_rollout(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        compose_id="cmp-591",
        previous_deployment_ids={"old-dep"},
        timeout_seconds=30,
    )

    out = capsys.readouterr().out
    assert "compose-error-attempt-1" in out
    assert "stale error" in out
    assert "new_deployment_ids=dep-592" in out


def test_AC8_13_72_dokploy_failure_log_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"message":"failed","refreshToken":"secret-refresh"}\n500',
            stderr="curl stderr without secret",
        )

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)

    with pytest.raises(RuntimeError, match="compose.update"):
        lifecycle.dokploy_api_call(
            lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
            "POST",
            "compose.update",
            payload={"composeId": "cmp-1"},
        )

    err = capsys.readouterr().err
    assert "endpoint=compose.update" in err
    assert "http_code: 500" in err
    assert "safe_message: failed" in err
    assert "raw_body_printed: false" in err
    assert "secret-refresh" not in err
    assert "secret-key" not in err


def test_AC8_13_71_preview_compose_project_uses_safe_deterministic_name() -> None:
    lifecycle = lifecycle_module()

    assert lifecycle.preview_compose_project(591) == "finance_report_pr_591"


def test_AC8_13_71_preview_image_tag_includes_pr_number_and_commit_sha() -> None:
    """AC8.13.71: PR preview image tags are commit-specific to avoid stale mutable deploys."""
    lifecycle = lifecycle_module()

    assert lifecycle.preview_image_tag(591, "abc123") == "pr-591-abc123"


def test_AC8_13_71_create_compose_requires_compose_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(lifecycle, "dokploy_api_call", lambda *args, **kwargs: "{}")

    with pytest.raises(RuntimeError, match="composeId"):
        lifecycle.create_compose(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            environment_id="env-test",
            compose_name="pr-591",
            pr_number=591,
            branch="feature",
            github_integration_id="ghid",
        )


def test_AC8_13_102_preview_source_disables_dokploy_auto_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: CI owns PR preview rollouts; Dokploy push auto-deploy is disabled."""
    lifecycle = lifecycle_module()
    payloads: list[dict[str, object]] = []

    def fake_dokploy_api_call(
        config,
        method,
        endpoint,
        *,
        payload=None,
        expected_status=200,
    ) -> str:
        assert config.api_url == "https://cloud.example/api"
        assert method == "POST"
        assert expected_status == 200
        if endpoint in {"compose.create", "compose.update"}:
            assert payload is not None
            payloads.append(payload)
        if endpoint == "compose.create":
            return '{"composeId":"cmp-591"}'
        return "{}"

    monkeypatch.setattr(lifecycle, "dokploy_api_call", fake_dokploy_api_call)

    lifecycle.create_compose(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        environment_id="env-test",
        compose_name="pr-591",
        pr_number=591,
        branch="feature",
        github_integration_id="ghid",
    )
    lifecycle.update_compose_source(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        compose_id="cmp-591",
        pr_number=591,
        branch="feature",
        github_integration_id="ghid",
    )

    assert [payload["autoDeploy"] for payload in payloads] == [False, False]


def test_AC8_13_71_get_or_create_reuses_existing_compose(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle, "find_compose_id_by_name", lambda *args, **kwargs: "cmp-591"
    )

    compose_id = lifecycle.get_or_create_compose(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        environment_id="env-test",
        compose_name="pr-591",
        pr_number=591,
        branch="feature",
        github_integration_id="ghid",
    )

    assert compose_id == "cmp-591"
    assert "Found existing compose: cmp-591" in capsys.readouterr().out


def test_AC8_13_72_update_compose_env_fails_when_effective_env_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle, "dokploy_api_call", lambda *args, **kwargs: '{"ok":true}'
    )
    monkeypatch.setattr(
        lifecycle, "get_compose_env", lambda *args, **kwargs: "IMAGE_TAG=old"
    )

    with pytest.raises(RuntimeError, match="effective environment"):
        lifecycle.update_compose_env(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            compose_id="cmp-591",
            env={
                "IMAGE_TAG": "pr-591-abc123",
                "GIT_COMMIT_SHA": "abc123",
                "IAC_CONFIG_HASH": "pr-591-abc123",
                "COMPOSE_PROJECT_NAME": "finance_report_pr_591",
                "ENV_SUFFIX": "-pr-591-abc123",
                "ENV_DOMAIN_SUFFIX": "-pr-591-abc123",
                "NETWORK_SUFFIX": "-pr-591",
                "NEXT_PUBLIC_API_URL": "https://report-pr-591-abc123.zitian.party",
                "DB_HOST": "finance-report-db-pr-591-abc123",
                "S3_HOST": "finance-report-minio-pr-591-abc123",
                "COMPOSE_PROFILES": "infra,app",
            },
        )


def test_AC8_13_71_cleanup_action_deletes_compose_without_ssh(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert input_text is None
        if "environment.one" in " ".join(cmd):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
    )
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
        dry_run=True,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "environment.one" in rendered_calls
    assert "compose.delete" in rendered_calls
    assert "compose.stop" not in rendered_calls
    assert "ssh" not in rendered_calls
    out = capsys.readouterr().out
    assert "Raw Dokploy response" not in out
    assert "secret-key" not in out


def test_AC8_13_71_cleanup_action_is_idempotent_when_compose_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle, "find_compose_id_by_name", lambda *args, **kwargs: None
    )
    args = SimpleNamespace(
        action="cleanup",
        pr_number=591,
        compose_name="pr-591",
        compose_id="",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="secret-key",
        dry_run=True,
    )

    assert lifecycle.cleanup_action(args) == 0

    assert "Compose not found: pr-591" in capsys.readouterr().out


def test_AC8_13_71_delete_action_is_idempotent_when_compose_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle, "find_compose_id_by_name", lambda *args, **kwargs: None
    )
    args = SimpleNamespace(
        action="delete",
        pr_number=591,
        compose_name="pr-591",
        compose_id="",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="secret-key",
    )

    assert lifecycle.main_from_args(args) == 0

    assert "Compose not found: pr-591" in capsys.readouterr().out


def test_AC8_13_72_deploy_action_reads_effective_env_before_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
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
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"compose":[]}', stderr=""
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"cmp-591"}', stderr=""
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"env": effective_env, "composeStatus": "running"}),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
    )
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


def test_AC8_13_102_new_preview_redeploys_when_initial_deploy_record_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: New PR previews retry with redeploy when Dokploy loses the deploy record."""
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []
    wait_calls = 0

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"compose":[]}', stderr=""
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"cmp-591"}', stderr=""
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {"env": effective_env, "composeStatus": "idle", "deployments": []}
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        assert kwargs.get("new_deployment_timeout_seconds") == 120
        if wait_calls == 1:
            raise lifecycle.DokployDeploymentDidNotStart("queued deploy was lost")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.deploy" in rendered_calls
    assert "compose.redeploy" in rendered_calls
    assert wait_calls == 2
    assert "retrying with compose.redeploy" in capsys.readouterr().out


def test_AC8_13_102_existing_preview_without_deployments_is_recreated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Existing empty preview composes are recreated before rollout."""
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"empty-cmp"}]}',
                stderr="",
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"recreated-cmp"}', stderr=""
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {"env": effective_env, "composeStatus": "idle", "deployments": []}
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.delete" in rendered_calls
    assert "compose.create" in rendered_calls
    assert "compose.deploy" in rendered_calls
    assert "compose.redeploy" not in rendered_calls
    assert "recreating before deploy" in capsys.readouterr().out


def test_AC8_13_102_existing_preview_rollout_tracks_new_deployment_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: Existing PR previews gate readiness on the new rollout."""
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []
    rollout_previous_ids: list[set[str] | None] = []

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
                stderr="",
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "env": effective_env,
                        "composeStatus": "running",
                        "deployments": [{"deploymentId": "old-dep-591"}],
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        previous = kwargs.get("previous_deployment_ids")
        rollout_previous_ids.append(previous if isinstance(previous, set) else None)

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0
    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.redeploy" in rendered_calls
    assert "compose.start" not in rendered_calls
    assert rollout_previous_ids == [{"old-dep-591"}]
    assert "VAULT_APP_TOKEN" not in rendered_calls
    assert "MINIO_ROOT_PASSWORD" not in rendered_calls


def test_AC8_13_102_existing_preview_missing_deploy_record_recreates_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: A stuck existing preview is recreated once before readiness."""
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []
    wait_calls = 0

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
                stderr="",
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"cmp-591-recreated"}', stderr=""
            )
        if "compose.one?composeId=cmp-591-recreated" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "env": effective_env,
                        "composeStatus": "idle",
                        "deployments": [],
                    }
                ),
                stderr="",
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "env": effective_env,
                        "composeStatus": "idle",
                        "deployments": [{"deploymentId": "old-dep-591"}],
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise lifecycle.DokployDeploymentDidNotStart("queued deploy was lost")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.redeploy" in rendered_calls
    assert "compose.delete" in rendered_calls
    assert "compose.create" in rendered_calls
    assert "compose.deploy" in rendered_calls
    assert wait_calls == 2
    out = capsys.readouterr().out
    assert "recreating compose before retry" in out
    assert "proceeding to commit-scoped readiness" not in out


def test_AC8_13_102_recreated_preview_missing_record_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Missing Dokploy records fail before public readiness."""
    lifecycle = lifecycle_module()
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    calls: list[list[str]] = []
    wait_calls = 0

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
                stderr="",
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"cmp-591-recreated"}', stderr=""
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "env": effective_env,
                    "composeStatus": "idle",
                    "deployments": [],
                }
            ),
            stderr="",
        )

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        raise lifecycle.DokployDeploymentDidNotStart("deployment record missing")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 1

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.redeploy" in rendered_calls
    assert "compose.delete" in rendered_calls
    assert "compose.create" in rendered_calls
    assert "compose.deploy" in rendered_calls
    assert wait_calls == 2
    out = capsys.readouterr().out
    assert "platform_failure_domain=dokploy-control-plane-record-missing" in out
    assert "readiness will not start" in out
    assert "raw_deployment_printed: false" in out
    assert "app_url=https://report-pr-591-abc123.zitian.party" not in out


def test_AC8_13_102_existing_preview_rollout_error_recreates_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: A failed rollout from an existing preview is recreated once."""
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []
    wait_calls = 0

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
                stderr="",
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"cmp-591-recreated"}', stderr=""
            )
        if "compose.one?composeId=cmp-591-recreated" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "env": effective_env,
                        "composeStatus": "idle",
                        "deployments": [],
                    }
                ),
                stderr="",
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "env": effective_env,
                        "composeStatus": "error",
                        "deployments": [{"deploymentId": "dep-591", "status": "error"}],
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise lifecycle.DokployDeploymentFailed("compose source checkout failed")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.redeploy" in rendered_calls
    assert "compose.delete" in rendered_calls
    assert "compose.create" in rendered_calls
    assert "compose.deploy" in rendered_calls
    assert wait_calls == 2


def test_AC8_13_102_new_preview_missing_after_redeploy_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Missing Dokploy records fail after one new-preview redeploy retry."""
    lifecycle = lifecycle_module()
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    calls: list[list[str]] = []
    wait_calls = 0

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[]}',
                stderr="",
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"cmp-591"}', stderr=""
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "env": effective_env,
                        "composeStatus": "idle",
                        "deployments": [],
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        raise lifecycle.DokployDeploymentDidNotStart("new deploy was lost")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 1

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert rendered_calls.count("compose.create") == 1
    assert "compose.delete" not in rendered_calls
    assert "compose.redeploy" in rendered_calls
    assert "compose.deploy" in rendered_calls
    assert wait_calls == 2
    out = capsys.readouterr().out
    assert "platform_failure_domain=dokploy-control-plane-record-missing" in out
    assert "readiness will not start" in out
    assert "new deploy was lost" in out
    assert "app_url=https://report-pr-591-abc123.zitian.party" not in out


def test_AC8_13_102_new_preview_rollout_error_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: A new preview rollout error is not hidden by recreate fallback."""
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"compose":[]}', stderr=""
            )
        if "compose.create" in rendered:
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"composeId":"cmp-591"}', stderr=""
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"env": effective_env, "composeStatus": "error"}),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        raise lifecycle.DokployDeploymentFailed("new rollout failed")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 1

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert rendered_calls.count("compose.create") == 1
    assert "compose.delete" not in rendered_calls
    assert "compose.redeploy" not in rendered_calls
    assert "compose.deploy" in rendered_calls


def test_AC8_13_98_existing_preview_compose_is_redeployed_without_pre_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.98: Existing PR previews redeploy without disrupting active routes."""
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []

    effective_env = "\n".join(
        [
            "IMAGE_TAG=pr-591-abc123",
            "GIT_COMMIT_SHA=abc123",
            "IAC_CONFIG_HASH=pr-591-abc123",
            "COMPOSE_PROJECT_NAME=finance_report_pr_591",
            "ENV_SUFFIX=-pr-591-abc123",
            "ENV_DOMAIN_SUFFIX=-pr-591-abc123",
            "NETWORK_SUFFIX=-pr-591",
            "NEXT_PUBLIC_API_URL=https://report-pr-591-abc123.zitian.party",
            "DB_HOST=finance-report-db-pr-591-abc123",
            "S3_HOST=finance-report-minio-pr-591-abc123",
            "COMPOSE_PROFILES=infra,app",
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
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
                stderr="",
            )
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"env": effective_env, "composeStatus": "running"}),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
    )
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
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0

    rendered_calls = "\n".join(" ".join(call) for call in calls)
    assert "compose.delete" not in rendered_calls
    assert "compose.create" not in rendered_calls
    assert "compose.update" in rendered_calls
    assert "compose.one" in rendered_calls
    assert "compose.stop" not in rendered_calls
    assert "compose.redeploy" in rendered_calls
    assert "compose.start" not in rendered_calls
    assert "secret-key" not in rendered_calls


def test_AC8_13_100_pr_preview_api_readiness_logs_route_diagnostics() -> None:
    """AC8.13.100: Readiness logs split frontend, API route, and backend domains."""
    workflow = (ROOT / ".github/workflows/pr-test.yml").read_text()
    deploy_block = workflow.split("  deploy:", 1)[1].split("  cleanup:", 1)[0]

    assert 'PYTHONUNBUFFERED: "1"' in workflow
    assert "python3 -u - << 'EOF'" in deploy_block
    assert "timeout-minutes: 12" in deploy_block
    assert "subprocess.run(" in deploy_block
    assert '"--max-time"' in deploy_block
    assert "subprocess_timeout_seconds = 20" in deploy_block
    assert "__FINANCE_REPORT_HTTP_STATUS__" in deploy_block
    assert '"Accept: application/json"' in deploy_block
    assert "route_probe attempt=" in deploy_block
    assert "app_readiness_classification=" in deploy_block
    assert "platform_failure_domain=" in deploy_block
    assert "write_readiness_context(" in deploy_block
    assert "pr-preview-readiness-context.json" in deploy_block
    assert '"failure_domain": failure_domain' in deploy_block
    assert '"last_api_status": str(api_result["status"])' in deploy_block
    assert '"last_frontend_status": str(frontend_result["status"])' in deploy_block
    assert "api_content_type=" in deploy_block
    assert "api_body_bytes=" in deploy_block
    assert "api_body_prefix=" in deploy_block
    assert '"body": body,' in deploy_block
    assert '"body": body[:500]' not in deploy_block
    assert "repo/tools/dokploy_route_canary.py" in deploy_block
    assert "frontend-fallback-api-route-missing-or-backend-unhealthy" in deploy_block
    assert "backend-health-missing-sha" in deploy_block
    assert "frontend-route-ready-api-route-missing" in deploy_block
    assert "dokploy-worker-or-deployment-record" in deploy_block
    assert "traefik-public-route" in deploy_block
    assert "readiness_timeout_seconds = 600" in deploy_block
    assert "elapsed_seconds=" in deploy_block
    assert "ping_status=" in deploy_block
    assert (
        "classified_route_failures >= 8 and not route_failure_notice_printed"
        in deploy_block
    )
    assert 'if failure_domain == "traefik-public-route":' in deploy_block
    assert "route_failure_notice_printed = True" in deploy_block
    assert (
        "::notice::API route is still unavailable after frontend served" in deploy_block
    )
    assert (
        "::error::API route stayed unavailable after frontend served"
        not in deploy_block
    )


def test_AC8_13_100_infra2_route_canary_is_available() -> None:
    """AC8.13.100: The infra2 submodule exposes the platform route canary."""
    canary_tool = ROOT / "repo/tools/dokploy_route_canary.py"
    canary_tests = ROOT / "repo/libs/tests/test_dokploy_route_canary.py"

    assert canary_tool.exists()
    assert canary_tests.exists()
    assert (
        "Dokploy dynamic route canary"
        in (ROOT / "repo/docs/ssot/ops.alerting.md").read_text()
    )


def test_AC8_13_71_deploy_action_writes_github_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lifecycle = lifecycle_module()
    output_path = tmp_path / "github-output.txt"

    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(
        lifecycle,
        "get_or_create_compose_with_status",
        lambda *args, **kwargs: ("cmp-591", False),
    )
    monkeypatch.setattr(
        lifecycle, "update_compose_source", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(lifecycle, "update_compose_env", lambda *args, **kwargs: None)
    monkeypatch.setattr(lifecycle, "deploy_compose", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        lifecycle, "print_compose_summary", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(lifecycle, "get_compose_data", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        lifecycle, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
    )
    args = SimpleNamespace(
        pr_number=591,
        compose_name="pr-591",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="secret-key",
        github_integration_id="ghid",
        branch="feature",
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        internal_domain="zitian.party",
    )

    assert lifecycle.deploy_action(args) == 0

    assert output_path.read_text() == (
        "compose_id=cmp-591\napp_url=https://report-pr-591-abc123.zitian.party\n"
    )


def test_AC8_13_107_deploy_action_fails_fast_on_missing_required_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.107: Missing deploy inputs fail before any Dokploy API call."""
    lifecycle = lifecycle_module()
    calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return "{}"

    monkeypatch.setattr(lifecycle, "dokploy_api_call", fail_if_called)
    args = SimpleNamespace(
        pr_number=591,
        compose_name="pr-591",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="",
        github_integration_id="",
        branch="feature",
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        internal_domain="zitian.party",
    )

    with pytest.raises(ValueError, match="api_key, github_integration_id"):
        lifecycle.deploy_action(args)

    assert calls == 0


def test_AC8_13_107_preview_deploy_context_is_written_without_secrets(
    tmp_path: Path,
) -> None:
    """AC8.13.107: Deploy context artifacts contain routing evidence, not credentials."""
    lifecycle = lifecycle_module()
    context_path = tmp_path / "ci-context" / "pr-preview-deploy-context.json"
    context_path.parent.mkdir(parents=True)
    context_path.write_text('{"old_secret":"do-not-preserve"}\n', encoding="utf-8")
    args = SimpleNamespace(
        pr_number=591,
        compose_name="pr-591",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="secret-key",
        github_integration_id="ghid-secret",
        branch="feature",
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        internal_domain="zitian.party",
    )

    lifecycle.write_preview_context(
        str(context_path),
        lifecycle.build_preview_context(
            args,
            phase="failed",
            compose_id="cmp-591",
            error="AUTHORIZATION=Bearer secret-token hvs.secret",
        ),
    )

    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["phase"] == "failed"
    assert context["compose_id"] == "cmp-591"
    assert context["expected_sha"] == "abc123"
    assert context["api_health_url"] == (
        "https://report-pr-591-abc123.zitian.party/api/health"
    )
    assert context["frontend_version_url"] == (
        "https://report-pr-591-abc123.zitian.party/"
        "frontend-version.json?expected=abc123"
    )
    assert (
        context["backend_image"] == "ghcr.io/owner/finance_report-backend:pr-591-abc123"
    )
    assert "api_key" not in context
    assert "github_integration_id" not in context
    rendered = json.dumps(context)
    assert "secret-key" not in rendered
    assert "ghid-secret" not in rendered
    assert "secret-token" not in rendered
    assert "hvs.secret" not in rendered
    assert "do-not-preserve" not in rendered


def test_AC8_13_107_pr_preview_workflow_fast_fails_missing_images_and_uploads_context() -> (
    None
):
    """AC8.13.107: PR preview logs deploy context and checks images before Dokploy."""
    workflow = (ROOT / ".github/workflows/pr-test.yml").read_text()
    deploy_block = workflow.split("  deploy:", 1)[1].split("  cleanup:", 1)[0]

    assert "packages: read" in deploy_block
    assert "- name: Preflight PR preview image tags" in deploy_block
    assert "docker buildx imagetools inspect" in deploy_block
    assert "Both PR preview images are available before Dokploy deploy." in deploy_block
    assert (
        "PR_PREVIEW_CONTEXT_PATH: ci-context/pr-preview-deploy-context.json"
        in deploy_block
    )
    assert (
        "preview_commit_slug=${{ needs.setup.outputs.preview_commit_slug }}"
        in deploy_block
    )
    assert "platform_triage=deploy context JSON" in deploy_block
    assert "ci-context/" in deploy_block


def test_AC8_13_101_pr_test_workflow_uses_commit_scoped_preview_url() -> None:
    """AC8.13.101: Readiness and E2E consume the deployed preview URL output."""
    workflow = (ROOT / ".github/workflows/pr-test.yml").read_text()
    deploy_block = workflow.split("  deploy:", 1)[1].split("  cleanup:", 1)[0]

    assert "preview_app_url: ${{ steps.info.outputs.preview_app_url }}" in workflow
    assert "preview_commit_slug" in workflow
    assert "NEXT_PUBLIC_API_URL=${{ needs.setup.outputs.preview_app_url }}" in workflow
    assert "NEXT_PUBLIC_APP_URL=${{ needs.setup.outputs.preview_app_url }}" in workflow
    assert "- name: Print preview routing context" in deploy_block
    assert "APP_URL: ${{ steps.deploy.outputs.app_url }}" in deploy_block
    assert 'context_app_url="${APP_URL}"' in deploy_block
    assert 'context_app_url="$(read_deploy_context_field app_url)"' in deploy_block
    assert 'echo "app_url=${context_app_url}"' in deploy_block
    assert "api_health_url=${context_app_url}/api/health" in (
        deploy_block
    )
    assert deploy_block.count("APP_URL: ${{ steps.deploy.outputs.app_url }}") >= 4
    assert "https://report-pr-${{ needs.setup.outputs.pr_number }}" not in deploy_block


def test_AC8_13_74_reconcile_deletes_only_stale_dokploy_composes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    deleted: list[str] = []

    monkeypatch.setattr(lifecycle, "list_open_pr_numbers", lambda: {591})
    monkeypatch.setattr(
        lifecycle,
        "list_preview_composes",
        lambda config, environment_id: {591: "cmp-591", 592: "cmp-592"},
    )
    monkeypatch.setattr(
        lifecycle,
        "delete_compose",
        lambda config, *, compose_id: deleted.append(compose_id),
    )
    args = SimpleNamespace(
        action="reconcile",
        pr_number=0,
        compose_name="",
        compose_id="",
        environment_id="env-test",
        api_url="https://cloud.example/api",
        api_key="secret-key",
        dry_run=False,
    )

    assert lifecycle.main_from_args(args) == 0

    assert deleted == ["cmp-592"]


def test_AC8_13_74_pr_number_listing_and_dokploy_compose_parsers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []

    assert lifecycle.parse_open_pr_numbers("591\n\n592\n") == {591, 592}

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="591\n592\n", stderr="")

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)

    assert lifecycle.list_open_pr_numbers() == {591, 592}
    assert lifecycle.parse_preview_pr_from_compose_name("pr-591") == 591
    assert lifecycle.parse_preview_pr_from_compose_name("not-pr-591") is None

    rendered = "\n".join(" ".join(call) for call in calls)
    assert "gh pr list" in rendered


def test_AC8_13_74_list_preview_composes_reads_dokploy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle,
        "dokploy_api_call",
        lambda *args, **kwargs: json.dumps(
            {
                "compose": [
                    {"name": "pr-591", "composeId": "cmp-591"},
                    {"name": "pr-592", "composeId": "cmp-592"},
                    {"name": "staging", "composeId": "cmp-staging"},
                ]
            }
        ),
    )

    assert lifecycle.list_preview_composes(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        "env-test",
    ) == {591: "cmp-591", 592: "cmp-592"}


def test_AC8_13_71_main_rejects_unsupported_action() -> None:
    lifecycle = lifecycle_module()

    with pytest.raises(ValueError, match="Unsupported action"):
        lifecycle.main_from_args(SimpleNamespace(action="unsupported"))


def test_AC8_13_74_scheduled_cleanup_only_reconciles_closed_prs() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert "tools/pr_preview_lifecycle.py" in workflow
    assert "--action reconcile" in workflow
    assert "tools/cleanup_pr_preview_resources.py" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journalctl" not in workflow
    assert "VPS_SSH_KEY" not in workflow
    assert "ssh-keyscan" not in workflow


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
    assert "VPS_SSH_KEY" not in cleanup_block
    assert "ssh-keyscan" not in cleanup_block


def test_AC8_13_74_close_cleanup_notice_does_not_claim_host_volume_cleanup() -> None:
    workflow = (ROOT / ".github/workflows/pr-test.yml").read_text()

    cleanup_block = workflow.split("  cleanup:", 1)[1]
    assert "Docker Volumes" not in cleanup_block
    assert "postgres_data, minio_data" not in cleanup_block
    assert "Host Docker leftovers" in cleanup_block
    assert "Dokploy host hygiene schedule" in cleanup_block


def test_AC8_13_102_api_call_retries_transient_failures_on_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: dokploy_api_call retries GET requests on transient network/server errors."""
    lifecycle = lifecycle_module()
    calls = 0

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls < 3:
            # Return transient 502 status code
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"message":"Bad Gateway"}\n502',
                stderr="curl transient error",
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"ok":true}\n200',
            stderr="",
        )

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setenv("DOKPLOY_API_RETRY_DELAY_SECONDS", "0.0")

    # GET request should succeed on 3rd attempt
    res = lifecycle.dokploy_api_call(
        lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
        "GET",
        "environment.one?environmentId=env-1",
    )
    assert res == '{"ok":true}'
    assert calls == 3

    # POST request should not retry and fail immediately
    calls = 0
    with pytest.raises(RuntimeError):
        lifecycle.dokploy_api_call(
            lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
            "POST",
            "compose.update",
            payload={"composeId": "cmp-1"},
        )
    assert calls == 1


def test_AC8_13_102_cleanup_and_delete_actions_ignore_api_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: cleanup_action and delete_action ignore API exceptions and return 0."""
    lifecycle = lifecycle_module()

    def fake_find_compose_id(*args: object, **kwargs: object) -> str:
        raise RuntimeError("Transient API connection failure")

    monkeypatch.setattr(lifecycle, "find_compose_id_by_name", fake_find_compose_id)

    # Both actions should catch the exception and return 0
    cleanup_res = lifecycle.cleanup_action(
        SimpleNamespace(
            api_url="https://cloud.example/api",
            api_key="secret",
            compose_id=None,
            environment_id="env-1",
            compose_name="pr-123",
        )
    )
    assert cleanup_res == 0

    delete_res = lifecycle.delete_action(
        SimpleNamespace(
            api_url="https://cloud.example/api",
            api_key="secret",
            compose_id=None,
            environment_id="env-1",
            compose_name="pr-123",
        )
    )
    assert delete_res == 0


def test_AC8_13_102_dokploy_api_call_invalid_retry_delay_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: Fallback to default retry delay when DOKPLOY_API_RETRY_DELAY_SECONDS is invalid."""
    import time
    lifecycle = lifecycle_module()
    calls = 0

    def fake_run_command(
        cmd: list[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls < 2:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"message":"Bad Gateway"}\n502',
                stderr="curl transient error",
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"ok":true}\n200',
            stderr="",
        )

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    # Set to invalid float
    monkeypatch.setenv("DOKPLOY_API_RETRY_DELAY_SECONDS", "invalid-float")

    start_time = time.monotonic()
    res = lifecycle.dokploy_api_call(
        lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
        "GET",
        "environment.one?environmentId=env-1",
    )
    end_time = time.monotonic()
    assert res == '{"ok":true}'
    assert calls == 2
    # Verify delay fallback (it should sleep 2.0s)
    assert end_time - start_time >= 1.9


def test_AC8_13_102_dokploy_api_call_non_transient_curl_error_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: Non-timeout curl error should not trigger transient retry."""
    lifecycle = lifecycle_module()
    calls = 0

    def fake_run_command(
        cmd: list[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        # exit code 7 = CURLE_COULDNT_CONNECT, which is not 28 (timeout)
        return subprocess.CompletedProcess(
            cmd,
            7,
            stdout="",
            stderr="curl: (7) Failed to connect to host",
        )

    monkeypatch.setattr(lifecycle, "run_command", fake_run_command)
    monkeypatch.setenv("DOKPLOY_API_RETRY_DELAY_SECONDS", "0.0")

    with pytest.raises(RuntimeError):
        lifecycle.dokploy_api_call(
            lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
            "GET",
            "environment.one?environmentId=env-1",
        )
    # Should fail immediately on 1st attempt, not retrying up to 4 times
    assert calls == 1


def test_AC8_13_102_cleanup_and_delete_actions_do_not_swallow_non_api_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: Non-RuntimeError exceptions are not swallowed by cleanup_action and delete_action."""
    lifecycle = lifecycle_module()

    def fake_find_compose_id(*args: object, **kwargs: object) -> str:
        # A programming/TypeError, not a RuntimeError
        raise TypeError("Unexpected argument type")

    monkeypatch.setattr(lifecycle, "find_compose_id_by_name", fake_find_compose_id)

    with pytest.raises(TypeError):
        lifecycle.cleanup_action(
            SimpleNamespace(
                api_url="https://cloud.example/api",
                api_key="secret",
                compose_id=None,
                environment_id="env-1",
                compose_name="pr-123",
            )
        )

    with pytest.raises(TypeError):
        lifecycle.delete_action(
            SimpleNamespace(
                api_url="https://cloud.example/api",
                api_key="secret",
                compose_id=None,
                environment_id="env-1",
                compose_name="pr-123",
            )
        )

