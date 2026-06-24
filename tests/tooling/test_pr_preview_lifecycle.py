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
    # COMPOSE_PROJECT_NAME is no longer injected: the docker compose project is
    # Dokploy's appName (see preview_compose_command), so overriding it here is
    # what orphaned merged-PR containers (compose.delete downs by appName).
    assert "COMPOSE_PROJECT_NAME" not in env
    assert env["PR_PREVIEW_CREATED_BY"] == "github-actions"
    assert env["IMAGE_TAG"] == "pr-591-abc123"
    assert env["GIT_COMMIT_SHA"] == "abc123"
    assert env["ENV_SUFFIX"] == "-pr-591-abc123"
    assert env["ENV_DOMAIN_SUFFIX"] == "-pr-591-abc123"
    assert env["NETWORK_SUFFIX"] == "-pr-591"
    assert env["NEXT_PUBLIC_API_URL"] == "https://report-pr-591.zitian.party"
    assert env["NEXT_PUBLIC_APP_URL"] == "https://report-pr-591.zitian.party"
    assert env["DB_HOST"] == "finance-report-db-pr-591-abc123"
    assert env["S3_HOST"] == "finance-report-minio-pr-591-abc123"
    assert env["S3_ENDPOINT"] == "http://finance-report-minio-pr-591-abc123:9000"
    assert env["COMPOSE_PROFILES"] == "infra,app"


def test_AC8_13_101_preview_app_url_prefers_stable_alias() -> None:
    """AC8.13.101: PR preview readiness targets a stable PR-level route."""
    lifecycle = lifecycle_module()

    assert lifecycle.preview_commit_slug("ABC123xyz456789") == "abc123xyz456"
    assert (
        lifecycle.preview_app_url(591, "ABC123xyz456789", "zitian.party")
        == "https://report-pr-591.zitian.party"
    )
    assert lifecycle.preview_port_offset(
        591, "abc123"
    ) != lifecycle.preview_port_offset(591, "def456")
    # The compose project MUST be Dokploy's appName so compose.delete (which
    # downs the stack by appName) reaps every container instead of orphaning it.
    assert lifecycle.preview_compose_command("compose-pr-591-xyz") == (
        "compose -p compose-pr-591-xyz -f docker-compose.pr-preview.yml "
        "up -d --build --remove-orphans"
    )
    # The project-less placeholder (create-time only) carries no `-p`; it is
    # always overwritten by update_compose_source before any deploy.
    assert lifecycle.preview_compose_command() == (
        "compose -f docker-compose.pr-preview.yml up -d --build --remove-orphans"
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
        "NEXT_PUBLIC_API_URL": "https://report-pr-591.zitian.party",
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
        lifecycle._dokploy, "get_compose_data", lambda *args, **kwargs: next(states)
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

    assert "previous_deployment_signatures" in signature.parameters
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
        lifecycle._dokploy, "get_compose_data", lambda *args, **kwargs: next(states)
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
        lifecycle._dokploy,
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
        lifecycle._dokploy,
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
        lifecycle._dokploy, "get_compose_data", lambda *args, **kwargs: next(states)
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


def test_AC8_13_102_existing_record_can_rollout_in_place(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Reused deployment records can still complete rollout readiness."""
    lifecycle = lifecycle_module()
    states = iter(
        [
            {
                "composeId": "cmp-591",
                "composeStatus": "running",
                "deployments": [
                    {
                        "deploymentId": "old-dep",
                        "status": "running",
                        "createdAt": "2026-01-01T00:00:00Z",
                        "startedAt": "2026-01-01T00:00:10Z",
                    },
                ],
            },
            {
                "composeId": "cmp-591",
                "composeStatus": "done",
                "deployments": [
                    {
                        "deploymentId": "old-dep",
                        "status": "done",
                        "createdAt": "2026-01-01T00:00:00Z",
                        "startedAt": "2026-01-01T00:00:10Z",
                        "finishedAt": "2026-01-01T00:00:20Z",
                    },
                ],
            },
        ]
    )

    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_compose_data",
        lambda *args, **kwargs: next(states),
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)
    compose_data = {
        "deployments": [
            {
                "deploymentId": "old-dep",
                "status": "running",
                "createdAt": "2026-01-01T00:00:00Z",
                "startedAt": "2026-01-01T00:00:10Z",
            },
        ]
    }

    lifecycle.wait_for_dokploy_deployment_rollout(
        lifecycle.DokployConfig("https://cloud.example/api", "secret"),
        compose_id="cmp-591",
        previous_deployment_ids={"old-dep"},
        previous_deployment_signatures=lifecycle.deployment_signatures(
            compose_data["deployments"]
        ),
        timeout_seconds=1,
    )

    out = capsys.readouterr().out
    assert "Dokploy rollout observed as existing deployment record update" in out


def test_AC8_13_102_existing_record_error_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Reused deployment record failure raises rollout error."""
    lifecycle = lifecycle_module()
    states = iter(
        [
            {
                "composeId": "cmp-591",
                "composeStatus": "running",
                "deployments": [
                    {
                        "deploymentId": "old-dep",
                        "status": "running",
                        "createdAt": "2026-01-01T00:00:00Z",
                        "startedAt": "2026-01-01T00:00:10Z",
                    },
                ],
            },
            {
                "composeId": "cmp-591",
                "composeStatus": "done",
                "deployments": [
                    {
                        "deploymentId": "old-dep",
                        "status": "error",
                        "createdAt": "2026-01-01T00:00:00Z",
                        "startedAt": "2026-01-01T00:00:10Z",
                    },
                ],
            },
        ]
    )

    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_compose_data",
        lambda *args, **kwargs: next(states),
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)
    compose_data = {
        "deployments": [
            {
                "deploymentId": "old-dep",
                "status": "running",
                "createdAt": "2026-01-01T00:00:00Z",
                "startedAt": "2026-01-01T00:00:10Z",
            },
        ]
    }

    with pytest.raises(
        lifecycle.DokployDeploymentFailed,
        match="Dokploy deployment failed before readiness polling: compose_id=cmp-591 deployment_id=old-dep",
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            compose_id="cmp-591",
            previous_deployment_ids={"old-dep"},
            previous_deployment_signatures=lifecycle.deployment_signatures(
                compose_data["deployments"]
            ),
            timeout_seconds=1,
        )

    out = capsys.readouterr().out
    assert "existing-deployment-error-attempt-2" in out


def test_AC8_13_102_deployment_signatures_preserve_rollout_activity_fields() -> None:
    lifecycle = lifecycle_module()

    signatures = lifecycle.deployment_signatures(
        [
            {"deploymentId": "dep-1", "status": "running", "createdAt": "t1"},
            {
                "deploymentId": "dep-2",
                "createdAt": "t2",
                "startedAt": None,
                "status": "running",
                "finishedAt": None,
            },
            {"notDeployment": True},
        ]
    )

    assert signatures["dep-1"] == ("running", "t1", "", "")
    assert signatures["dep-2"] == ("running", "t2", "", "")


def test_AC8_13_102_rollout_timeout_uses_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setenv(
        lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
        "300",
    )
    assert (
        lifecycle.parse_positive_int_env(
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS,
        )
        == 300
    )
    monkeypatch.setenv(
        lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
        "not-a-number",
    )
    assert (
        lifecycle.parse_positive_int_env(
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS,
        )
        == lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS
    )
    monkeypatch.setenv(
        lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
        "0",
    )
    assert (
        lifecycle.parse_positive_int_env(
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS,
        )
        == lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS
    )
    monkeypatch.setenv(
        lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
        "-5",
    )
    assert (
        lifecycle.parse_positive_int_env(
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS,
        )
        == lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS
    )


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
            raise lifecycle.DokployRequestError(
                "Dokploy request failed for compose.one?api_key=secret"
            )
        return {
            "composeStatus": "done",
            "deployments": [{"deploymentId": "new-dep", "status": "done"}],
        }

    monkeypatch.setattr(lifecycle._dokploy, "get_compose_data", fake_get_compose_data)
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
        lifecycle._dokploy,
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
        lifecycle._dokploy, "get_compose_data", lambda *args, **kwargs: next(states)
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)

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
    """AC8.13.71: Legacy preview image tags stay commit-specific for cleanup."""
    lifecycle = lifecycle_module()

    assert lifecycle.preview_image_tag(591, "abc123") == "pr-591-abc123"


def test_AC8_13_71_create_compose_requires_compose_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", lambda *args, **kwargs: "{}")

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
        assert expected_status == 200
        # update_compose_source reads the appName via GET compose.one to scope
        # the deploy command; everything else is a POST mutation.
        if endpoint.startswith("compose.one"):
            assert method == "GET"
            return '{"appName":"compose-pr-591-app"}'
        assert method == "POST"
        if endpoint in {"compose.create", "compose.update"}:
            assert payload is not None
            payloads.append(payload)
        if endpoint == "compose.create":
            return '{"composeId":"cmp-591"}'
        return "{}"

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", fake_dokploy_api_call)

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
        branch="feature",
        github_integration_id="ghid",
    )

    # create uses the project-less placeholder; update rewrites it with the
    # appName-scoped command so teardown can reap the stack.
    assert [payload["autoDeploy"] for payload in payloads] == [False, False]
    create_payload, update_payload = payloads
    assert "-p " not in create_payload["command"]
    assert update_payload["command"] == (
        "compose -p compose-pr-591-app -f docker-compose.pr-preview.yml "
        "up -d --build --remove-orphans"
    )


def test_AC8_13_71_get_or_create_reuses_existing_compose(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()

    monkeypatch.setattr(
        lifecycle._dokploy, "find_compose_id_by_name", lambda *args, **kwargs: "cmp-591"
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
        lifecycle._dokploy, "dokploy_api_call", lambda *args, **kwargs: '{"ok":true}'
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_env", lambda *args, **kwargs: "IMAGE_TAG=old"
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
                "NEXT_PUBLIC_API_URL": "https://report-pr-591.zitian.party",
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
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
        lifecycle._dokploy, "find_compose_id_by_name", lambda *args, **kwargs: None
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
        lifecycle._dokploy, "find_compose_id_by_name", lambda *args, **kwargs: None
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                stdout=json.dumps(
                    {
                        "appName": "compose-pr-591-app",
                        "env": effective_env,
                        "composeStatus": "running",
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                    {
                        "appName": "compose-pr-591-app",
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
        assert kwargs.get("new_deployment_timeout_seconds") == 120
        if wait_calls == 1:
            raise lifecycle.DokployDeploymentDidNotStart("queued deploy was lost")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                    {
                        "appName": "compose-pr-591-app",
                        "env": effective_env,
                        "composeStatus": "idle",
                        "deployments": [],
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                        "appName": "compose-pr-591-app",
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                        "appName": "compose-pr-591-app",
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
                        "appName": "compose-pr-591-app",
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                    "appName": "compose-pr-591-app",
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
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
    assert wait_calls == 3
    out = capsys.readouterr().out
    assert (
        "New PR preview compose still did not create a Dokploy deployment record" in out
    )
    assert "platform_failure_domain=dokploy-control-plane-record-missing" in out
    assert "readiness will not start" in out
    assert "raw_deployment_printed: false" in out
    assert "app_url=https://report-pr-591.zitian.party" not in out


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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                        "appName": "compose-pr-591-app",
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
                        "appName": "compose-pr-591-app",
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
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


def test_AC8_13_102_new_preview_missing_after_redeploy_recreates_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: A stuck new preview compose is recreated once before failing."""
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                        "appName": "compose-pr-591-app",
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
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
    assert rendered_calls.count("compose.create") == 2
    assert "compose.delete" in rendered_calls
    assert "compose.redeploy" in rendered_calls
    assert "compose.deploy" in rendered_calls
    assert wait_calls == 3
    out = capsys.readouterr().out
    assert (
        "New PR preview compose still did not create a Dokploy deployment record" in out
    )
    assert "platform_failure_domain=dokploy-control-plane-record-missing" in out
    assert "readiness will not start" in out
    assert "new deploy was lost" in out
    assert "app_url=https://report-pr-591.zitian.party" not in out


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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                    {
                        "appName": "compose-pr-591-app",
                        "env": effective_env,
                        "composeStatus": "error",
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    def fake_wait_for_rollout(*args: object, **kwargs: object) -> None:
        raise lifecycle.DokployDeploymentFailed("new rollout failed")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait_for_rollout
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
            "NEXT_PUBLIC_API_URL=https://report-pr-591.zitian.party",
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
                        "appName": "compose-pr-591-app",
                        "env": effective_env,
                        "composeStatus": "running",
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
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


def test_AC8_13_100_pr_preview_runner_readiness_is_bounded_and_observable() -> None:
    """AC8.13.100: Runner preview readiness is bounded and logs stack failures."""
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]

    assert "workflow_run:" not in workflow
    assert 'PYTHONUNBUFFERED: "1"' in workflow
    assert "timeout-minutes: 25" in e2e_block
    assert "Wait for stack readiness" in e2e_block
    assert 'curl -fsS "$APP_URL/api/health"' in e2e_block
    assert "for i in $(seq 1 60)" in e2e_block
    assert "stack did not become healthy within 300s" in e2e_block
    assert "Stack logs on failure" in e2e_block
    assert "docker compose logs --no-color --tail=400" in e2e_block
    assert "preview_runtime=github-runner-compose" in e2e_block
    assert (
        "persistent_preview_url=${{ needs.setup.outputs.preview_app_url }}" in e2e_block
    )
    assert "registry_image_push=false" in e2e_block
    assert "dokploy_deploy=after-e2e-non-blocking-build-from-source" in e2e_block
    assert "route_probe attempt=" not in workflow
    assert "app_readiness_classification=" not in workflow
    assert "platform_failure_domain=" not in workflow
    assert "pr-preview-readiness-context.json" not in workflow


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
        lifecycle._dokploy,
        "get_or_create_compose_with_status",
        lambda *args, **kwargs: ("cmp-591", False),
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "update_compose_source", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(lifecycle._dokploy, "update_compose_env", lambda *args, **kwargs: None)
    monkeypatch.setattr(lifecycle._dokploy, "deploy_compose", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        lifecycle._dokploy, "print_compose_summary", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(lifecycle._dokploy, "get_compose_data", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", lambda *args, **kwargs: None
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
        "compose_id=cmp-591\napp_url=https://report-pr-591.zitian.party\n"
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

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", fail_if_called)
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


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("pr_number", -1, "positive pr_number"),
        ("image_prefix", "finance_report", "include the registry namespace"),
        ("internal_domain", "localhost", "must be a DNS name"),
    ],
)
def test_AC8_13_107_deploy_input_validation_rejects_invalid_values(
    field: str,
    value: object,
    expected_error: str,
) -> None:
    """AC8.13.107: Invalid deploy input values fail before rollout mutation."""
    lifecycle = lifecycle_module()
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
    setattr(args, field, value)

    with pytest.raises(ValueError, match=expected_error):
        lifecycle.validate_deploy_inputs(args)


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
        "https://report-pr-591.zitian.party/api/health"
    )
    assert context["frontend_version_url"] == (
        "https://report-pr-591.zitian.party/frontend-version.json?expected=abc123"
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


def test_AC8_13_107_empty_preview_context_path_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC8.13.107: Missing context path does not create stray local artifacts."""
    lifecycle = lifecycle_module()
    monkeypatch.chdir(tmp_path)

    lifecycle.write_preview_context("", {"phase": "preflight"})

    assert list(tmp_path.iterdir()) == []


def test_AC8_13_107_pr_preview_workflow_uploads_context_without_image_preflight() -> (
    None
):
    """AC8.13.107: PR preview uploads context and does not preflight PR images."""
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]
    cleanup_block = workflow.split("  cleanup:", 1)[1]

    deploy_block = workflow.split("  deploy-preview:", 1)[1].split("  e2e:", 1)[0]

    assert "docker/build-push-action@v7" not in workflow
    assert "- name: Preflight PR preview image tags" not in workflow
    assert "docker buildx imagetools inspect" not in workflow
    # The persistent deploy job writes its own context (no image preflight).
    assert (
        "PR_PREVIEW_CONTEXT_PATH: ci-context/pr-preview-deploy-context.json"
        in deploy_block
    )
    assert "registry_image_push=false" in e2e_block
    assert "dokploy_deploy=after-e2e-non-blocking-build-from-source" in e2e_block
    assert "preview_runtime=github-runner-compose" in e2e_block
    assert "pr_preview_images=not-created" in cleanup_block
    assert "test-results/" in e2e_block
    assert "ci-context/" in e2e_block


def test_AC8_13_101_pr_test_workflow_uses_runner_preview_url() -> None:
    """AC8.13.101: E2E consumes the runner-local preview URL."""
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]

    assert "preview_app_url: ${{ steps.info.outputs.preview_app_url }}" in workflow
    assert "preview_commit_slug" in workflow
    assert (
        "NEXT_PUBLIC_API_URL=${{ needs.setup.outputs.preview_app_url }}" not in workflow
    )
    assert (
        "NEXT_PUBLIC_APP_URL=${{ needs.setup.outputs.preview_app_url }}" not in workflow
    )
    assert "APP_URL: http://localhost:8080" in e2e_block
    assert "app_url=http://localhost:8080" in e2e_block
    assert "api_health_url=http://localhost:8080/api/health" in e2e_block
    # The in-runner E2E consumes the runner-local URL; the persistent Dokploy
    # preview URL is recorded for the separate non-blocking deploy job.
    assert (
        "persistent_preview_url=${{ needs.setup.outputs.preview_app_url }}" in e2e_block
    )
    assert "no PR preview image is pushed" in e2e_block
    assert "EXPECTED_SHA: ${{ needs.setup.outputs.head_sha }}" in e2e_block
    assert "APP_URL: ${{ steps.deploy.outputs.app_url }}" not in workflow


def test_AC8_13_74_reconcile_deletes_only_stale_dokploy_composes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    deleted: list[str] = []

    monkeypatch.setattr(lifecycle.cli, "list_open_pr_numbers", lambda: {591})
    monkeypatch.setattr(
        lifecycle._dokploy,
        "list_preview_composes",
        lambda config, environment_id: {591: "cmp-591", 592: "cmp-592"},
    )
    monkeypatch.setattr(
        lifecycle._dokploy,
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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)

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
        lifecycle._dokploy,
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
    workflow = (ROOT / ".github/workflows/maintenance.yml").read_text()

    assert "tools/pr_preview_lifecycle.py" in workflow
    assert "--action reconcile" in workflow
    assert "tools/cleanup_pr_preview_resources.py" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journalctl" not in workflow
    assert "VPS_SSH_KEY" not in workflow
    assert "ssh-keyscan" not in workflow


def test_AC8_13_71_pr_test_workflow_uses_lifecycle_for_cleanup() -> None:
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()

    assert "--action cleanup" in workflow
    assert "--action delete" not in workflow
    assert "compose.stop" not in workflow


def test_AC8_13_71_close_cleanup_checks_out_lifecycle_tool() -> None:
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()

    cleanup_block = workflow.split("  cleanup:", 1)[1]
    assert "uses: actions/checkout@v7" in cleanup_block
    assert cleanup_block.index("uses: actions/checkout@v7") < cleanup_block.index(
        "python tools/pr_preview_lifecycle.py"
    )
    assert "VPS_SSH_KEY" not in cleanup_block
    assert "ssh-keyscan" not in cleanup_block


def test_AC8_13_74_close_cleanup_notice_does_not_claim_host_volume_cleanup() -> None:
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()

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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
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
    """AC8.13.102: cleanup_action and delete_action ignore Dokploy API exceptions."""
    lifecycle = lifecycle_module()

    def fake_find_compose_id(*args: object, **kwargs: object) -> str:
        raise lifecycle.DokployRequestError("Transient API connection failure")

    monkeypatch.setattr(lifecycle._dokploy, "find_compose_id_by_name", fake_find_compose_id)

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
    lifecycle = lifecycle_module()
    calls = 0
    sleeps: list[float] = []

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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: sleeps.append(seconds))
    # Set to invalid float
    monkeypatch.setenv("DOKPLOY_API_RETRY_DELAY_SECONDS", "invalid-float")

    res = lifecycle.dokploy_api_call(
        lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
        "GET",
        "environment.one?environmentId=env-1",
    )
    assert res == '{"ok":true}'
    assert calls == 2
    assert sleeps == [2.0]


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

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
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
    """AC8.13.102: Non-Dokploy exceptions are not swallowed by cleanup/delete."""
    lifecycle = lifecycle_module()

    def fake_find_compose_id(*args: object, **kwargs: object) -> str:
        raise RuntimeError("Unexpected lifecycle bug")

    monkeypatch.setattr(lifecycle._dokploy, "find_compose_id_by_name", fake_find_compose_id)

    with pytest.raises(RuntimeError):
        lifecycle.cleanup_action(
            SimpleNamespace(
                api_url="https://cloud.example/api",
                api_key="secret",
                compose_id=None,
                environment_id="env-1",
                compose_name="pr-123",
            )
        )

    with pytest.raises(RuntimeError):
        lifecycle.delete_action(
            SimpleNamespace(
                api_url="https://cloud.example/api",
                api_key="secret",
                compose_id=None,
                environment_id="env-1",
                compose_name="pr-123",
            )
        )


def test_get_running_deployments_count(monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle = lifecycle_module()

    # Test valid JSON with running and deploying statuses
    fake_body = (
        '{"environments": ['
        '  {"compose": [{"composeStatus": "running"}, {"composeStatus": "deploying"}, {"composeStatus": "error"}]}'
        "]}"
    )
    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: fake_body)
    config = lifecycle.DokployConfig("https://cloud.example/api", "secret-key")
    assert lifecycle.get_running_deployments_count(config, "proj-123") == 2

    # Test exception handling (e.g. invalid JSON)
    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: "invalid json")
    assert lifecycle.get_running_deployments_count(config, "proj-123") == 0


def test_wait_for_dokploy_deployment_rollout_extends_deadline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.125: Busy Dokploy queues may extend only inside rollout budget."""
    lifecycle = lifecycle_module()

    # Mock time and sleep
    current_time = [1000.0]
    sleep_calls = []

    def fake_time() -> float:
        return current_time[0]

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        current_time[0] += seconds

    monkeypatch.setattr(lifecycle.time, "time", fake_time)
    monkeypatch.setattr(lifecycle.time, "monotonic", fake_time)
    monkeypatch.setattr(lifecycle.time, "sleep", fake_sleep)

    # get_compose_data returns composeStatus running, but no new deployments yet
    get_compose_data_calls = 0

    def fake_get_compose_data(*args, **kwargs):
        nonlocal get_compose_data_calls
        get_compose_data_calls += 1
        if get_compose_data_calls == 1:
            # First call: return running compose, no new deployment.
            # We mock time forward by 10.0 seconds so the next iteration's now will exceed the deadline.
            current_time[0] += 10.0
            return {
                "composeId": "cmp-1",
                "composeStatus": "running",
                "environment": {"projectId": "proj-123"},
                "deployments": [{"deploymentId": "old-dep", "status": "error"}],
            }
        elif get_compose_data_calls == 2:
            # Second call: still running, no new deployment.
            # now (1010.0) is >= new_deployment_deadline (1005.0), triggering extension.
            return {
                "composeId": "cmp-1",
                "composeStatus": "running",
                "environment": {"projectId": "proj-123"},
                "deployments": [{"deploymentId": "old-dep", "status": "error"}],
            }
        else:
            # Third call: new deployment found
            return {
                "composeId": "cmp-1",
                "composeStatus": "done",
                "environment": {"projectId": "proj-123"},
                "deployments": [
                    {"deploymentId": "old-dep", "status": "error"},
                    {"deploymentId": "dep-new", "status": "done"},
                ],
            }

    monkeypatch.setattr(lifecycle._dokploy, "get_compose_data", fake_get_compose_data)

    # Mock get_running_deployments_count to return 1 (busy)
    monkeypatch.setattr(lifecycle._dokploy, "get_running_deployments_count", lambda *a, **k: 1)

    lifecycle.wait_for_dokploy_deployment_rollout(
        lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
        compose_id="cmp-1",
        previous_deployment_ids={"old-dep"},
        new_deployment_timeout_seconds=5,
    )

    out = capsys.readouterr().out
    assert "Dokploy is currently busy with other deployments" in out
    assert "Extending the new deployment timeout deadline" in out


def test_AC8_13_125_busy_dokploy_queue_cannot_extend_past_rollout_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.125: PR preview rollout waits stay bounded when Dokploy is busy."""
    lifecycle = lifecycle_module()

    current_time = [1000.0]

    def fake_time() -> float:
        return current_time[0]

    def fake_sleep(seconds: float) -> None:
        current_time[0] += seconds

    def fake_get_compose_data(*args, **kwargs):
        return {
            "composeId": "cmp-1",
            "composeStatus": "running",
            "environment": {"projectId": "proj-123"},
            "deployments": [{"deploymentId": "old-dep", "status": "running"}],
        }

    monkeypatch.setattr(lifecycle.time, "time", fake_time)
    monkeypatch.setattr(lifecycle.time, "monotonic", fake_time)
    monkeypatch.setattr(lifecycle.time, "sleep", fake_sleep)
    monkeypatch.setattr(lifecycle._dokploy, "get_compose_data", fake_get_compose_data)
    monkeypatch.setattr(lifecycle._dokploy, "get_running_deployments_count", lambda *a, **k: 1)

    with pytest.raises(lifecycle.DokployDeploymentDidNotStart):
        lifecycle.wait_for_dokploy_deployment_rollout(
            lifecycle.DokployConfig("https://cloud.example/api", "secret-key"),
            compose_id="cmp-1",
            previous_deployment_ids={"old-dep"},
            timeout_seconds=10,
            new_deployment_timeout_seconds=5,
        )

    assert current_time[0] == 1010.0


def test_AC8_13_125_pr_preview_runner_lifecycle_has_hard_timeout() -> None:
    """AC8.13.125: GitHub caps PR preview runner lifecycle runtime."""
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]

    assert "timeout-minutes: 25" in e2e_block
    assert "for i in $(seq 1 60)" in e2e_block
    assert "stack did not become healthy within 300s" in e2e_block
    assert "docker compose down --volumes --remove-orphans --timeout 30" in e2e_block


# ---------------------------------------------------------------------------
# Issue #756 — fail-fast on no-new-deployment record (classified error)
# Issue #758 — rollback / safe-to-reconcile on mutate-then-fail
# ---------------------------------------------------------------------------


def _deploy_args() -> SimpleNamespace:
    return SimpleNamespace(
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


def test_AC7_13_1_no_new_deployment_record_raises_classified_subclass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC7.13.1: A done compose with no new deployment record fails fast with the
    dedicated DokployNoNewDeploymentRecord classified error (subclass of
    DokployDeploymentDidNotStart so the existing retry flow still catches it)."""
    lifecycle = lifecycle_module()

    assert issubclass(
        lifecycle.DokployNoNewDeploymentRecord,
        lifecycle.DokployDeploymentDidNotStart,
    )

    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_compose_data",
        lambda *args, **kwargs: {
            "composeStatus": "done",
            "deployments": [{"deploymentId": "old-dep"}],
        },
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)

    with pytest.raises(lifecycle.DokployNoNewDeploymentRecord) as excinfo:
        lifecycle.wait_for_dokploy_deployment_rollout(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            compose_id="cmp-1",
            previous_deployment_ids={"old-dep"},
            timeout_seconds=1,
            new_deployment_timeout_seconds=0,
        )

    assert "dokploy-worker-or-deployment-record" in str(excinfo.value)
    out = capsys.readouterr().out
    assert "proceeding to commit-scoped readiness" not in out
    # AC7.13.2: diagnostics distinguish "no new deployment created" from a
    # "route not ready" 404 window.
    assert "did not create a new deployment record" in out


def test_AC7_13_2_env_reconciliation_rejects_stale_non_allowlisted_keys() -> None:
    """AC7.13.2: Non-allowlisted stale keys lingering in the effective env are
    detected and the diagnostic names keys only (no secret values)."""
    lifecycle = lifecycle_module()

    requested = {"IMAGE_TAG": "pr-1-sha", "ZAI_API_KEY": "wanted"}
    effective = "\n".join(
        [
            "IMAGE_TAG=pr-1-sha",
            "ZAI_API_KEY=wanted",
            # leftover from a previous deploy, not in the requested env at all
            "STALE_TOKEN=leaked-secret-value",
        ]
    )

    divergent = lifecycle.env_reconciliation_divergence(requested, effective)
    assert "STALE_TOKEN" in divergent

    diff = lifecycle.render_env_reconciliation_diff(requested, effective)
    assert "STALE_TOKEN" in diff
    assert "leaked-secret-value" not in diff
    assert "raw_env_printed: false" in diff

    # A fully-matching env reconciles cleanly.
    clean = "\n".join(["IMAGE_TAG=pr-1-sha", "ZAI_API_KEY=wanted"])
    assert lifecycle.env_reconciliation_divergence(requested, clean) == []


def test_AC7_13_3_update_compose_env_fails_fast_on_stale_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7.13.3: update_compose_env fails fast when the effective remote env keeps
    a stale non-allowlisted key that diverges from the requested env."""
    lifecycle = lifecycle_module()

    requested = lifecycle.build_preview_env(
        pr_number=591,
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        internal_domain="zitian.party",
    )
    # Effective env echoes everything requested plus an orphan key.
    effective = lifecycle.render_env(requested) + "ORPHAN_LEFTOVER=stale\n"

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: "{}")
    monkeypatch.setattr(lifecycle._dokploy, "get_compose_env", lambda *a, **k: effective)

    with pytest.raises(RuntimeError, match="did not match requested deploy env"):
        lifecycle.update_compose_env(
            lifecycle.DokployConfig("https://cloud.example/api", "secret"),
            compose_id="cmp-1",
            env=requested,
        )


def test_AC7_13_4_mutate_then_fail_marks_state_and_records_step(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """AC7.13.4: When rollout fails after the compose was mutated, deploy_action
    leaves an explicitly-marked safe-to-reconcile state, records which mutation
    step it was left at, and does not silently report success."""
    lifecycle = lifecycle_module()
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    context_path = tmp_path / "context.json"
    monkeypatch.setenv(lifecycle.PR_PREVIEW_CONTEXT_ENV, str(context_path))

    good_env = lifecycle.render_env(
        lifecycle.build_preview_env(
            pr_number=591,
            commit_sha="prevsha",
            registry="ghcr.io",
            image_prefix="owner/finance_report",
            internal_domain="zitian.party",
        )
    )

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
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
        if "compose.one" in rendered:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "appName": "compose-pr-591-app",
                        "env": good_env,
                        "composeStatus": "done",
                        "deployments": [{"deploymentId": "old-dep-591"}],
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    # Make the mutation steps no-ops so we exercise the rollout-failure path.
    monkeypatch.setattr(lifecycle._dokploy, "update_compose_env", lambda *a, **k: None)
    monkeypatch.setattr(lifecycle._dokploy, "update_compose_source", lambda *a, **k: None)
    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)

    def fake_wait(*args: object, **kwargs: object) -> None:
        raise lifecycle.DokployDeploymentFailed("rollout never went healthy")

    monkeypatch.setattr(lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait)

    assert lifecycle.main_from_args(_deploy_args()) == 1

    context = json.loads(context_path.read_text())
    assert context["phase"] == "failed"
    # AC7.13.4: the mutation step the environment was left at is recorded.
    assert context.get("mutation_step") in {"deploy", "env", "source", "rollout"}
    # AC7.13.1/758: an explicitly-marked safe-to-reconcile or rolled-back state,
    # not a silent half-update.
    assert context.get("recovery_state") in {
        "rolled-back",
        "marked-safe-to-reconcile",
    }
    out = capsys.readouterr().out
    assert "PR preview deploy failed" in out


def test_AC7_13_4_existing_compose_rolls_back_to_last_known_good_on_env_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """AC7.13.4: An existing compose whose env update fails reconciliation is
    rolled back to its captured last-known-good source/env (not left half
    updated), recording the env mutation step it failed at."""
    lifecycle = lifecycle_module()
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    context_path = tmp_path / "context.json"
    monkeypatch.setenv(lifecycle.PR_PREVIEW_CONTEXT_ENV, str(context_path))

    last_known_good_env = "IMAGE_TAG=pr-591-prevsha\nGOOD_MARKER=keep\n"
    last_known_good_command = (
        "compose -p compose-pr-591-app -f docker-compose.pr-preview.yml up -d"
    )
    update_calls: list[dict[str, object]] = []

    def fake_run_command(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
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
                        "appName": "compose-pr-591-app",
                        "command": last_known_good_command,
                        "env": last_known_good_env,
                        "composeStatus": "done",
                        "deployments": [{"deploymentId": "old-dep-591"}],
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run_command)
    monkeypatch.setattr(lifecycle._dokploy, "update_compose_source", lambda *a, **k: None)

    # Capture the rollback compose.update payload directly.
    original_api_call = lifecycle.dokploy_api_call

    def spy_api_call(config, method, endpoint, *, payload=None, expected_status=200):
        if endpoint == "compose.update" and payload is not None:
            update_calls.append(dict(payload))
            return "{}"
        return original_api_call(
            config, method, endpoint, payload=payload, expected_status=expected_status
        )

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", spy_api_call)

    # Effective env keeps a stale non-allowlisted key, so update_compose_env
    # raises the reconciliation RuntimeError after the snapshot was captured.
    def fake_get_compose_env(config, *, compose_id):
        requested = lifecycle.build_preview_env(
            pr_number=591,
            commit_sha="abc123",
            registry="ghcr.io",
            image_prefix="owner/finance_report",
            internal_domain="zitian.party",
        )
        return lifecycle.render_env(requested) + "STALE_LEFTOVER=old\n"

    monkeypatch.setattr(lifecycle._dokploy, "get_compose_env", fake_get_compose_env)

    assert lifecycle.main_from_args(_deploy_args()) == 1

    context = json.loads(context_path.read_text())
    assert context["phase"] == "failed"
    assert context.get("mutation_step") == "env"
    assert context.get("recovery_state") == "rolled-back"
    # The rollback restored the captured last-known-good env/command.
    rollback = update_calls[-1]
    assert rollback.get("env") == last_known_good_env
    assert rollback.get("command") == last_known_good_command
    out = capsys.readouterr().out
    assert "Rolled compose back to last-known-good" in out


def test_AC7_13_5_ci_cd_docs_describe_failure_modes() -> None:
    """AC7.13.5: ci-cd SSOT documents both the no-new-deployment fail-fast mode
    and the half-update rollback / safe-to-reconcile recovery path."""
    ci_cd = (ROOT / "docs/ssot/ci-cd.md").read_text()
    assert "dokploy-worker-or-deployment-record" in ci_cd
    assert "safe-to-reconcile" in ci_cd
    lowered = ci_cd.lower()
    assert "no new deployment" in lowered
    assert "rollback" in lowered or "roll back" in lowered
