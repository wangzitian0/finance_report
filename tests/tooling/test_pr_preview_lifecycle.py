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


DEFAULT_EFFECTIVE_ENV = "\n".join(
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


def _deploy_args(**overrides: object) -> SimpleNamespace:
    payload: dict[str, object] = {
        "action": "deploy",
        "pr_number": 591,
        "compose_name": "pr-591",
        "compose_id": "",
        "environment_id": "env-test",
        "api_url": "https://cloud.example/api",
        "api_key": "secret-key",
        "github_integration_id": "ghid",
        "branch": "feature",
        "commit_sha": "abc123",
        "registry": "ghcr.io",
        "image_prefix": "owner/finance_report",
        "internal_domain": "zitian.party",
        "dry_run": False,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _make_fake_runner(
    calls: list[list[str]] | None = None,
    responses: dict[str, str | dict[str, object]] | None = None,
    default: str = '{"ok":true}',
):
    mapping = responses or {}

    def fake_run_command(
        cmd: list[str], *, input_text: str | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append(cmd)
        rendered = " ".join(cmd)
        for key, val in mapping.items():
            if key in rendered:
                out = val if isinstance(val, str) else json.dumps(val)
                return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=default, stderr="")

    return fake_run_command


def _cfg(url: str = "https://cloud.example/api", key: str = "secret") -> object:
    return lifecycle_module().DokployConfig(url, key)


def _dep(
    dep_id: str = "dep-591",
    status: str = "done",
    created: str = "2026-01-01T00:00:00Z",
    started: str = "2026-01-01T00:00:10Z",
    **extra: object,
) -> dict[str, object]:
    d: dict[str, object] = {
        "deploymentId": dep_id,
        "status": status,
        "createdAt": created,
        "startedAt": started,
    }
    d.update(extra)
    return d


def _cmp(
    status: str = "idle",
    deployments: list[dict[str, object]] | None = None,
    compose_id: str = "cmp-591",
    app_name: str = "compose-pr-591-app",
    env: str = DEFAULT_EFFECTIVE_ENV,
    **extra: object,
) -> dict[str, object]:
    d: dict[str, object] = {
        "composeId": compose_id,
        "composeStatus": status,
        "appName": app_name,
        "env": env,
        "deployments": deployments or [],
    }
    d.update(extra)
    return d


def _run_deploy_step(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, str | dict[str, object]],
    *,
    wait_hook: object | None = None,
    deploy_args: SimpleNamespace | None = None,
    default: str = '{"ok":true}',
) -> tuple[int, str, list[list[str]]]:
    lifecycle = lifecycle_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        lifecycle._util,
        "run_command",
        _make_fake_runner(calls, responses, default=default),
    )
    if wait_hook is not None:
        monkeypatch.setattr(
            lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", wait_hook
        )
    else:
        monkeypatch.setattr(
            lifecycle._dokploy,
            "wait_for_dokploy_deployment_rollout",
            lambda *args, **kwargs: None,
        )
    args = deploy_args or _deploy_args()
    code = lifecycle.main_from_args(args)
    rendered = "\n".join(" ".join(c) for c in calls)
    return code, rendered, calls


def test_AC8_13_71_preview_env_contains_stable_metadata() -> None:
    lifecycle = lifecycle_module()
    env = lifecycle.build_preview_env(
        pr_number=591,
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="wangzitian0/finance_report",
        internal_domain="zitian.party",
    )
    expected = {
        "PR_PREVIEW_PR_NUMBER": "591",
        "PR_PREVIEW_COMPOSE_NAME": "pr-591",
        "PR_PREVIEW_COMPOSE_PROJECT": "finance_report_pr_591",
        "PR_PREVIEW_CREATED_BY": "github-actions",
        "IMAGE_TAG": "pr-591-abc123",
        "GIT_COMMIT_SHA": "abc123",
        "ENV_SUFFIX": "-pr-591-abc123",
        "ENV_DOMAIN_SUFFIX": "-pr-591-abc123",
        "NETWORK_SUFFIX": "-pr-591",
        "NEXT_PUBLIC_API_URL": "https://report-pr-591.zitian.party",
        "NEXT_PUBLIC_APP_URL": "https://report-pr-591.zitian.party",
        "DB_HOST": "finance-report-db-pr-591-abc123",
        "S3_HOST": "finance-report-minio-pr-591-abc123",
        "S3_ENDPOINT": "http://finance-report-minio-pr-591-abc123:9000",
        "COMPOSE_PROFILES": "infra,app",
    }
    assert "COMPOSE_PROJECT_NAME" not in env
    for k, v in expected.items():
        assert env[k] == v


def test_AC8_13_101_preview_app_url_prefers_stable_alias() -> None:
    """AC-testing.preview.10: AC8.13.101: PR preview readiness targets a stable PR-level route."""
    lifecycle = lifecycle_module()
    assert lifecycle.preview_commit_slug("ABC123xyz456789") == "abc123xyz456"
    assert (
        lifecycle.preview_app_url(591, "ABC123xyz456789", "zitian.party")
        == "https://report-pr-591.zitian.party"
    )
    assert lifecycle.preview_port_offset(
        591, "abc123"
    ) != lifecycle.preview_port_offset(591, "def456")
    assert lifecycle.preview_compose_command("compose-pr-591-xyz") == (
        "compose -p compose-pr-591-xyz -f docker-compose.pr-preview.yml up -d --build --remove-orphans"
    )
    assert lifecycle.preview_compose_command() == (
        "compose -f docker-compose.pr-preview.yml up -d --build --remove-orphans"
    )


def test_AC8_13_102_preview_network_is_pr_scoped_to_limit_subnet_usage() -> None:
    """AC-testing.preview.11: AC8.13.102: PR previews do not allocate one Docker network per commit."""
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
    for secret in ("hvs.secret", "refresh-secret", "postgres://secret", "DATABASE_URL"):
        assert secret not in diff


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
    for expected in (
        "Dokploy compose summary (after-deploy-trigger)",
        "composeId: cmp-591",
        "branch: feature",
        "composeStatus: running",
        "deployment_count: 1",
        "latest_deployment_deploymentId: dep-591",
        "latest_deployment_error: image pull failed token=<redacted>",
        "latest_deployment_errorMessage: network creation failed",
        "latest_deployment_logPath: /etc/dokploy/logs/compose-pr-591.log",
        "env_present: True",
        "raw_compose_printed: false",
        "raw_deployment_printed: false",
    ):
        assert expected in summary
    for hidden in (
        "postgres://secret",
        "refreshToken",
        "DATABASE_URL",
        "secret-refresh",
        "hvs.secret",
    ):
        assert hidden not in summary


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
            _cmp("idle"),
            _cmp("running", [_dep("dep-591", "running")]),
            _cmp("done", [_dep("dep-591", "done")]),
        ]
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_data", lambda *a, **k: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda seconds: None)

    lifecycle.wait_for_dokploy_deployment_rollout(
        _cfg(),
        compose_id="cmp-591",
        previous_deployment_ids={"old-dep"},
        timeout_seconds=30,
    )
    out = capsys.readouterr().out
    for s in (
        "deployment-rollout-attempt-1",
        "Dokploy rollout probe: attempt=1",
        "Dokploy rollout probe: attempt=2",
        "Dokploy rollout probe: attempt=3",
        "Dokploy deployment observed: compose_id=cmp-591",
        "new_deployment_ids=dep-591",
        "latest_deployment_status=running",
        "latest_deployment_status=done",
    ):
        assert s in out


def test_AC8_13_102_dokploy_rollout_record_window_allows_worker_queue() -> None:
    """AC8.13.102: The deployment-record gate is fast, but not shorter than Dokploy queue lag."""
    signature = inspect.signature(
        lifecycle_module().wait_for_dokploy_deployment_rollout
    )
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
            _cmp("idle"),
            _cmp("running", [_dep("dep-591", "running")]),
            _cmp("running", [_dep("dep-591", "running")]),
            _cmp("done", [_dep("dep-591", "done")]),
        ]
    )
    times = iter([0.0, 590.0, 610.0, 620.0, 630.0])
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_data", lambda *a, **k: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)

    lifecycle.wait_for_dokploy_deployment_rollout(
        _cfg(),
        compose_id="cmp-591",
        previous_deployment_ids={"old-dep"},
    )


def test_AC8_13_102_dokploy_rollout_timeout_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_data", lambda *a, **k: _cmp("idle")
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)
    times = iter([0.0, 2.0])
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(times))

    with pytest.raises(
        lifecycle.DokployDeploymentDidNotStart,
        match="did not create a new deployment before readiness",
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            _cfg(), compose_id="cmp-591", timeout_seconds=1
        )


def test_AC8_13_102_dokploy_rollout_error_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_compose_data",
        lambda *a, **k: _cmp("running", [_dep("dep-591", "error")]),
    )
    with pytest.raises(RuntimeError, match="deployment failed before readiness"):
        lifecycle.wait_for_dokploy_deployment_rollout(
            _cfg(), compose_id="cmp-591", previous_deployment_ids={"old-dep"}
        )


def test_AC8_13_102_done_compose_without_new_record_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Done composes with old records fail before app readiness."""
    lifecycle = lifecycle_module()
    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_compose_data",
        lambda *a, **k: {
            "composeStatus": "done",
            "deployments": [{"deploymentId": "old-dep"}],
        },
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)

    with pytest.raises(
        lifecycle.DokployDeploymentDidNotStart,
        match="did not create a new deployment record for this rollout",
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            _cfg(),
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
            _cmp("running", [_dep("old-dep", "running")]),
            _cmp("done", [_dep("old-dep", "done", finishedAt="2026-01-01T00:00:20Z")]),
        ]
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_data", lambda *a, **k: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)
    compose_data = {"deployments": [_dep("old-dep", "running")]}

    lifecycle.wait_for_dokploy_deployment_rollout(
        _cfg(),
        compose_id="cmp-591",
        previous_deployment_ids={"old-dep"},
        previous_deployment_signatures=lifecycle.deployment_signatures(
            compose_data["deployments"]
        ),
        timeout_seconds=1,
    )
    assert (
        "Dokploy rollout observed as existing deployment record update"
        in capsys.readouterr().out
    )


def test_AC8_13_102_existing_record_error_fails_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Reused deployment record failure raises rollout error."""
    lifecycle = lifecycle_module()
    states = iter(
        [
            _cmp("running", [_dep("old-dep", "running")]),
            _cmp("done", [_dep("old-dep", "error")]),
        ]
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_data", lambda *a, **k: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)
    compose_data = {"deployments": [_dep("old-dep", "running")]}

    with pytest.raises(
        lifecycle.DokployDeploymentFailed,
        match="Dokploy deployment failed before readiness polling: compose_id=cmp-591 deployment_id=old-dep",
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            _cfg(),
            compose_id="cmp-591",
            previous_deployment_ids={"old-dep"},
            previous_deployment_signatures=lifecycle.deployment_signatures(
                compose_data["deployments"]
            ),
            timeout_seconds=1,
        )
    assert "existing-deployment-error-attempt-2" in capsys.readouterr().out


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


@pytest.mark.parametrize(
    ("val", "expected"),
    [
        ("300", 300),
        ("not-a-number", 120),
        ("0", 120),
        ("-5", 120),
    ],
)
def test_AC8_13_102_rollout_timeout_uses_environment_override(
    monkeypatch: pytest.MonkeyPatch, val: str, expected: int
) -> None:
    lifecycle = lifecycle_module()
    monkeypatch.setenv(lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV, val)
    assert (
        lifecycle.parse_positive_int_env(
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
            lifecycle.PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS,
        )
        == expected
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
        return {"composeStatus": "done", "deployments": [_dep("new-dep", "done")]}

    monkeypatch.setattr(lifecycle._dokploy, "get_compose_data", fake_get_compose_data)
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)
    lifecycle.wait_for_dokploy_deployment_rollout(
        _cfg(), compose_id="cmp-1", previous_deployment_ids=set(), timeout_seconds=10
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
    err_dep = _dep(
        "dep-591",
        "error",
        error="docker compose failed: pull access denied AUTHORIZATION=Bearer secret-token hvs.secret",
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_data", lambda *a, **k: _cmp("error", [err_dep])
    )

    with pytest.raises(
        RuntimeError, match="compose entered error status before readiness polling"
    ):
        lifecycle.wait_for_dokploy_deployment_rollout(
            _cfg(), compose_id="cmp-591", previous_deployment_ids={"old-dep"}
        )

    out = capsys.readouterr().out
    for s in (
        "compose-error-attempt-1",
        "latest_deployment_deploymentId: dep-591",
        "latest_deployment_error: docker compose failed: pull access denied",
        "AUTHORIZATION=<redacted>",
        "raw_deployment_printed: false",
    ):
        assert s in out
    assert "secret-token" not in out and "hvs.secret" not in out


def test_AC8_13_102_stale_compose_error_waits_for_new_rollout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle = lifecycle_module()
    states = iter(
        [
            _cmp("error", [_dep("old-dep", "error", description="Commit: old-sha")]),
            _cmp(
                "done",
                [
                    _dep("old-dep", "error"),
                    _dep("dep-592", "done", description="Commit: new-sha"),
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_data", lambda *a, **k: next(states)
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)
    lifecycle.wait_for_dokploy_deployment_rollout(
        _cfg(),
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
    monkeypatch.setattr(
        lifecycle._util,
        "run_command",
        lambda cmd, **k: subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"message":"failed","refreshToken":"secret-refresh"}\n500',
            stderr="curl stderr without secret",
        ),
    )
    with pytest.raises(RuntimeError, match="compose.update"):
        lifecycle.dokploy_api_call(
            _cfg(key="secret-key"),
            "POST",
            "compose.update",
            payload={"composeId": "cmp-1"},
        )

    err = capsys.readouterr().err
    for s in (
        "endpoint=compose.update",
        "http_code: 500",
        "safe_message: failed",
        "raw_body_printed: false",
    ):
        assert s in err
    assert "secret-refresh" not in err and "secret-key" not in err


def test_AC8_13_71_preview_compose_project_uses_safe_deterministic_name() -> None:
    assert lifecycle_module().preview_compose_project(591) == "finance_report_pr_591"


def test_AC8_13_71_preview_image_tag_includes_pr_number_and_commit_sha() -> None:
    """AC8.13.71: Legacy preview image tags stay commit-specific for cleanup."""
    assert lifecycle_module().preview_image_tag(591, "abc123") == "pr-591-abc123"


def test_AC8_13_71_create_compose_requires_compose_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = lifecycle_module()
    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: "{}")
    with pytest.raises(RuntimeError, match="composeId"):
        lifecycle.create_compose(
            _cfg(),
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
        config, method, endpoint, *, payload=None, expected_status=200
    ) -> str:
        assert config.api_url == "https://cloud.example/api" and expected_status == 200
        if endpoint.startswith("compose.one"):
            assert method == "GET"
            return '{"appName":"compose-pr-591-app"}'
        assert method == "POST"
        if endpoint in {"compose.create", "compose.update"}:
            assert payload is not None
            payloads.append(payload)
        return '{"composeId":"cmp-591"}' if endpoint == "compose.create" else "{}"

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", fake_dokploy_api_call)
    cfg = _cfg()
    lifecycle.create_compose(
        cfg,
        environment_id="env-test",
        compose_name="pr-591",
        pr_number=591,
        branch="feature",
        github_integration_id="ghid",
    )
    lifecycle.update_compose_source(
        cfg, compose_id="cmp-591", branch="feature", github_integration_id="ghid"
    )

    assert [payload["autoDeploy"] for payload in payloads] == [False, False]
    create_payload, update_payload = payloads
    assert "-p " not in create_payload["command"]
    assert (
        update_payload["command"]
        == "compose -p compose-pr-591-app -f docker-compose.pr-preview.yml up -d --build --remove-orphans"
    )


def test_AC8_13_71_get_or_create_reuses_existing_compose(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lifecycle = lifecycle_module()
    monkeypatch.setattr(
        lifecycle._dokploy, "find_compose_id_by_name", lambda *a, **k: "cmp-591"
    )
    compose_id = lifecycle.get_or_create_compose(
        _cfg(),
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
        lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: '{"ok":true}'
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_env", lambda *a, **k: "IMAGE_TAG=old"
    )
    with pytest.raises(RuntimeError, match="effective environment"):
        lifecycle.update_compose_env(
            _cfg(),
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


def test_AC8_13_72_deploy_action_reads_effective_env_before_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effective_env = f"{DEFAULT_EFFECTIVE_ENV}\nVAULT_APP_TOKEN=hvs.secret"
    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[]}',
            "compose.create": '{"composeId":"cmp-591"}',
            "compose.one": {
                "appName": "compose-pr-591-app",
                "env": effective_env,
                "composeStatus": "running",
            },
        },
        deploy_args=_deploy_args(
            host="cloud.zitian.party", user="root", ssh_key="/tmp/key"
        ),
    )
    assert code == 0
    for kw in ("compose.update", "compose.one", "compose.deploy"):
        assert kw in calls
    assert "secret-key" not in calls


def test_AC8_13_102_new_preview_redeploys_when_initial_deploy_record_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: New PR previews retry with redeploy when Dokploy loses the deploy record."""
    lifecycle = lifecycle_module()
    wait_calls = 0

    def fake_wait(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        assert kwargs.get("new_deployment_timeout_seconds") == 120
        if wait_calls == 1:
            raise lifecycle.DokployDeploymentDidNotStart("queued deploy was lost")

    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[]}',
            "compose.create": '{"composeId":"cmp-591"}',
            "compose.one": _cmp("idle"),
        },
        wait_hook=fake_wait,
    )
    assert code == 0
    assert "compose.deploy" in calls and "compose.redeploy" in calls
    assert wait_calls == 2
    assert "retrying with compose.redeploy" in capsys.readouterr().out


def test_AC8_13_102_existing_preview_without_deployments_is_recreated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: Existing empty preview composes are recreated before rollout."""
    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"empty-cmp"}]}',
            "compose.create": '{"composeId":"recreated-cmp"}',
            "compose.one": _cmp("idle"),
        },
    )
    assert code == 0
    for kw in ("compose.delete", "compose.create", "compose.deploy"):
        assert kw in calls
    assert "compose.redeploy" not in calls
    assert "recreating before deploy" in capsys.readouterr().out


def test_AC8_13_102_existing_preview_rollout_tracks_new_deployment_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: Existing PR previews gate readiness on the new rollout."""
    rollout_previous_ids: list[set[str] | None] = []

    def fake_wait(*args: object, **kwargs: object) -> None:
        previous = kwargs.get("previous_deployment_ids")
        rollout_previous_ids.append(previous if isinstance(previous, set) else None)

    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
            "compose.one": _cmp("running", [_dep("old-dep-591")]),
        },
        wait_hook=fake_wait,
    )
    assert code == 0
    assert "compose.redeploy" in calls and "compose.start" not in calls
    assert rollout_previous_ids == [{"old-dep-591"}]
    assert "VAULT_APP_TOKEN" not in calls and "MINIO_ROOT_PASSWORD" not in calls


def test_AC8_13_102_existing_preview_missing_deploy_record_recreates_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: A stuck existing preview is recreated once before readiness."""
    lifecycle = lifecycle_module()
    wait_calls = 0

    def fake_wait(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise lifecycle.DokployDeploymentDidNotStart("queued deploy was lost")

    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
            "compose.create": '{"composeId":"cmp-591-recreated"}',
            "compose.one?composeId=cmp-591-recreated": _cmp("idle"),
            "compose.one": _cmp("idle", [_dep("old-dep-591")]),
        },
        wait_hook=fake_wait,
    )
    assert code == 0
    for kw in (
        "compose.redeploy",
        "compose.delete",
        "compose.create",
        "compose.deploy",
    ):
        assert kw in calls
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
    wait_calls = 0

    def fake_wait(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        raise lifecycle.DokployDeploymentDidNotStart("deployment record missing")

    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
            "compose.create": '{"composeId":"cmp-591-recreated"}',
        },
        wait_hook=fake_wait,
        default=json.dumps(_cmp("idle")),
    )
    assert code == 1
    for kw in (
        "compose.redeploy",
        "compose.delete",
        "compose.create",
        "compose.deploy",
    ):
        assert kw in calls
    assert wait_calls == 3
    out = capsys.readouterr().out
    for s in (
        "New PR preview compose still did not create a Dokploy deployment record",
        "platform_failure_domain=dokploy-control-plane-record-missing",
        "readiness will not start",
        "raw_deployment_printed: false",
    ):
        assert s in out
    assert "app_url=https://report-pr-591.zitian.party" not in out


def test_AC8_13_102_existing_preview_rollout_error_recreates_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: A failed rollout from an existing preview is recreated once."""
    lifecycle = lifecycle_module()
    wait_calls = 0

    def fake_wait(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise lifecycle.DokployDeploymentFailed("compose source checkout failed")

    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
            "compose.create": '{"composeId":"cmp-591-recreated"}',
            "compose.one?composeId=cmp-591-recreated": _cmp("idle"),
            "compose.one": _cmp("error", [_dep("dep-591", "error")]),
        },
        wait_hook=fake_wait,
    )
    assert code == 0
    for kw in (
        "compose.redeploy",
        "compose.delete",
        "compose.create",
        "compose.deploy",
    ):
        assert kw in calls
    assert wait_calls == 2


def test_AC8_13_102_new_preview_missing_after_redeploy_recreates_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.102: A stuck new preview compose is recreated once before failing."""
    lifecycle = lifecycle_module()
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    wait_calls = 0

    def fake_wait(*args: object, **kwargs: object) -> None:
        nonlocal wait_calls
        wait_calls += 1
        raise lifecycle.DokployDeploymentDidNotStart("new deploy was lost")

    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[]}',
            "compose.create": '{"composeId":"cmp-591"}',
            "compose.one": _cmp("idle"),
        },
        wait_hook=fake_wait,
    )
    assert code == 1
    assert calls.count("compose.create") == 2
    for kw in ("compose.delete", "compose.redeploy", "compose.deploy"):
        assert kw in calls
    assert wait_calls == 3
    out = capsys.readouterr().out
    for s in (
        "New PR preview compose still did not create a Dokploy deployment record",
        "platform_failure_domain=dokploy-control-plane-record-missing",
        "readiness will not start",
        "new deploy was lost",
    ):
        assert s in out
    assert "app_url=https://report-pr-591.zitian.party" not in out


def test_AC8_13_102_new_preview_rollout_error_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: A new preview rollout error is not hidden by recreate fallback."""
    lifecycle = lifecycle_module()

    def fake_wait(*args: object, **kwargs: object) -> None:
        raise lifecycle.DokployDeploymentFailed("new rollout failed")

    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[]}',
            "compose.create": '{"composeId":"cmp-591"}',
            "compose.one": {
                "appName": "compose-pr-591-app",
                "env": DEFAULT_EFFECTIVE_ENV,
                "composeStatus": "error",
            },
        },
        wait_hook=fake_wait,
    )
    assert code == 1
    assert calls.count("compose.create") == 1
    assert (
        "compose.delete" not in calls
        and "compose.redeploy" not in calls
        and "compose.deploy" in calls
    )


def test_AC8_13_98_existing_preview_compose_is_redeployed_without_pre_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.preview.8: AC8.13.98: Existing PR previews redeploy without disrupting active routes."""
    code, calls, _ = _run_deploy_step(
        monkeypatch,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
            "compose.one": {
                "appName": "compose-pr-591-app",
                "env": DEFAULT_EFFECTIVE_ENV,
                "composeStatus": "running",
            },
        },
    )
    assert code == 0
    for kw in ("compose.update", "compose.one", "compose.redeploy"):
        assert kw in calls
    for forbidden in (
        "compose.delete",
        "compose.create",
        "compose.stop",
        "compose.start",
        "secret-key",
    ):
        assert forbidden not in calls


def test_AC8_13_100_pr_preview_runner_readiness_is_bounded_and_observable() -> None:
    """AC-testing.preview.9: AC8.13.100: Runner preview readiness is bounded and logs stack failures."""
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]
    assert 'PYTHONUNBUFFERED: "1"' in workflow
    for s in (
        "timeout-minutes: 25",
        "Wait for stack readiness",
        'curl -fsS "$APP_URL/api/health"',
        "for i in $(seq 1 60)",
        "stack did not become healthy within 300s",
        "Stack logs on failure",
        "docker compose logs --no-color --tail=400",
        "preview_runtime=github-runner-compose",
        "persistent_preview_url=${{ needs.setup.outputs.preview_app_url }}",
        "registry_image_push=false",
        "dokploy_deploy=after-e2e-non-blocking-build-from-source",
    ):
        assert s in e2e_block
    for hidden in (
        "workflow_run:",
        "route_probe attempt=",
        "app_readiness_classification=",
        "platform_failure_domain=",
        "pr-preview-readiness-context.json",
    ):
        assert hidden not in workflow


def test_AC8_13_71_deploy_action_writes_github_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lifecycle = lifecycle_module()
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_or_create_compose_with_status",
        lambda *a, **k: ("cmp-591", False),
    )
    for method in (
        "update_compose_source",
        "update_compose_env",
        "deploy_compose",
        "print_compose_summary",
        "wait_for_dokploy_deployment_rollout",
    ):
        monkeypatch.setattr(lifecycle._dokploy, method, lambda *a, **k: None)
    monkeypatch.setattr(lifecycle._dokploy, "get_compose_data", lambda *a, **k: {})
    assert lifecycle.deploy_action(_deploy_args()) == 0
    assert (
        output_path.read_text()
        == "compose_id=cmp-591\napp_url=https://report-pr-591.zitian.party\n"
    )


def test_AC8_13_107_deploy_action_fails_fast_on_missing_required_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.preview.12: AC8.13.107: Missing deploy inputs fail before any Dokploy API call."""
    lifecycle = lifecycle_module()
    calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return "{}"

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", fail_if_called)
    with pytest.raises(ValueError, match="api_key, github_integration_id"):
        lifecycle.deploy_action(_deploy_args(api_key="", github_integration_id=""))
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
    field: str, value: object, expected_error: str
) -> None:
    """AC8.13.107: Invalid deploy input values fail before rollout mutation."""
    lifecycle = lifecycle_module()
    args = _deploy_args()
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
    args = _deploy_args(github_integration_id="ghid-secret")

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
    assert context["api_health_url"] == "https://report-pr-591.zitian.party/api/health"
    assert (
        context["frontend_version_url"]
        == "https://report-pr-591.zitian.party/frontend-version.json?expected=abc123"
    )
    assert (
        context["backend_image"] == "ghcr.io/owner/finance_report-backend:pr-591-abc123"
    )
    assert "api_key" not in context and "github_integration_id" not in context
    rendered = json.dumps(context)
    for hidden in (
        "secret-key",
        "ghid-secret",
        "secret-token",
        "hvs.secret",
        "do-not-preserve",
    ):
        assert hidden not in rendered


def test_AC8_13_107_empty_preview_context_path_is_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    assert 'PYTHONUNBUFFERED: "1"' in workflow
    cleanup_block = workflow.split("  cleanup:", 1)[1]
    deploy_block = workflow.split("  deploy-preview:", 1)[1].split("  e2e:", 1)[0]
    for hidden in (
        "docker/build-push-action@v7",
        "- name: Preflight PR preview image tags",
        "docker buildx imagetools inspect",
    ):
        assert hidden not in workflow
    assert (
        "PR_PREVIEW_CONTEXT_PATH: ci-context/pr-preview-deploy-context.json"
        in deploy_block
    )
    assert "registry_image_push=false" in e2e_block
    assert "dokploy_deploy=after-e2e-non-blocking-build-from-source" in e2e_block
    assert "preview_runtime=github-runner-compose" in e2e_block
    assert "pr_preview_images=not-created" in cleanup_block
    assert "test-results/" in e2e_block and "ci-context/" in e2e_block


def test_AC8_13_101_pr_test_workflow_uses_runner_preview_url() -> None:
    """AC8.13.101: E2E consumes the runner-local preview URL."""
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]
    assert 'PYTHONUNBUFFERED: "1"' in workflow
    assert "preview_app_url: ${{ steps.info.outputs.preview_app_url }}" in workflow
    assert "preview_commit_slug" in workflow
    for hidden in (
        "NEXT_PUBLIC_API_URL=${{ needs.setup.outputs.preview_app_url }}",
        "NEXT_PUBLIC_APP_URL=${{ needs.setup.outputs.preview_app_url }}",
        "APP_URL: ${{ steps.deploy.outputs.app_url }}",
    ):
        assert hidden not in workflow
    for s in (
        "APP_URL: http://localhost:8080",
        "app_url=http://localhost:8080",
        "api_health_url=http://localhost:8080/api/health",
        "persistent_preview_url=${{ needs.setup.outputs.preview_app_url }}",
        "no PR preview image is pushed",
        "EXPECTED_SHA: ${{ needs.setup.outputs.head_sha }}",
    ):
        assert s in e2e_block


def test_AC8_13_71_main_rejects_unsupported_action() -> None:
    with pytest.raises(ValueError, match="Unsupported action"):
        lifecycle_module().main_from_args(SimpleNamespace(action="unsupported"))


def test_AC8_13_71_deploy_still_uses_lifecycle_tool() -> None:
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    assert "--action deploy" in workflow
    for hidden in (
        "--action cleanup",
        "--action delete",
        "--action reconcile",
        "compose.stop",
    ):
        assert hidden not in workflow


def test_AC8_13_71_close_dispatches_preview_teardown_to_infra2() -> None:
    """AC-testing.preview.3: One lifecycle tool stands PR previews UP (deploy) and writes stable preview metadata."""
    workflow = (ROOT / ".github/workflows/preview.yml").read_text()
    cleanup_block = workflow.split("  cleanup:", 1)[1]
    assert (
        "preview-teardown" in cleanup_block
        and "repos/wangzitian0/infra2/dispatches" in cleanup_block
    )
    for hidden in ("DOKPLOY_API_KEY", "VPS_SSH_KEY", "ssh-keyscan"):
        assert hidden not in cleanup_block


def test_AC8_13_102_api_call_retries_transient_failures_on_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: dokploy_api_call retries GET requests on transient network/server errors."""
    lifecycle = lifecycle_module()
    calls = 0

    def fake_run(cmd: list[str], *, input_text: str | None = None, check: bool = True):
        nonlocal calls
        calls += 1
        if calls < 3:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"message":"Bad Gateway"}\n502',
                stderr="curl transient error",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}\n200', stderr="")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run)
    monkeypatch.setenv("DOKPLOY_API_RETRY_DELAY_SECONDS", "0.0")
    res = lifecycle.dokploy_api_call(
        _cfg(key="secret-key"), "GET", "environment.one?environmentId=env-1"
    )
    assert res == '{"ok":true}' and calls == 3

    calls = 0
    with pytest.raises(RuntimeError):
        lifecycle.dokploy_api_call(
            _cfg(key="secret-key"),
            "POST",
            "compose.update",
            payload={"composeId": "cmp-1"},
        )
    assert calls == 1


def test_AC8_13_102_dokploy_api_call_invalid_retry_delay_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: Fallback to default retry delay when DOKPLOY_API_RETRY_DELAY_SECONDS is invalid."""
    lifecycle = lifecycle_module()
    calls = 0
    sleeps: list[float] = []

    def fake_run(cmd: list[str], *, check: bool = True):
        nonlocal calls
        calls += 1
        if calls < 2:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"message":"Bad Gateway"}\n502',
                stderr="curl transient error",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok":true}\n200', stderr="")

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run)
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("DOKPLOY_API_RETRY_DELAY_SECONDS", "invalid-float")
    res = lifecycle.dokploy_api_call(
        _cfg(key="secret-key"), "GET", "environment.one?environmentId=env-1"
    )
    assert res == '{"ok":true}' and calls == 2 and sleeps == [2.0]


def test_AC8_13_102_dokploy_api_call_non_transient_curl_error_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.102: Non-timeout curl error should not trigger transient retry."""
    lifecycle = lifecycle_module()
    calls = 0

    def fake_run(cmd: list[str], *, check: bool = True):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            cmd, 7, stdout="", stderr="curl: (7) Failed to connect to host"
        )

    monkeypatch.setattr(lifecycle._util, "run_command", fake_run)
    monkeypatch.setenv("DOKPLOY_API_RETRY_DELAY_SECONDS", "0.0")
    with pytest.raises(RuntimeError):
        lifecycle.dokploy_api_call(
            _cfg(key="secret-key"), "GET", "environment.one?environmentId=env-1"
        )
    assert calls == 1


def test_get_running_deployments_count(monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle = lifecycle_module()
    fake_body = '{"environments": [{"compose": [{"composeStatus": "running"}, {"composeStatus": "deploying"}, {"composeStatus": "error"}]}]}'
    monkeypatch.setattr(
        lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: fake_body
    )
    config = _cfg(key="secret-key")
    assert lifecycle.get_running_deployments_count(config, "proj-123") == 2
    monkeypatch.setattr(
        lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: "invalid json"
    )
    assert lifecycle.get_running_deployments_count(config, "proj-123") == 0


def test_wait_for_dokploy_deployment_rollout_extends_deadline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.125: Busy Dokploy queues may extend only inside rollout budget."""
    lifecycle = lifecycle_module()
    current_time = [1000.0]
    sleep_calls: list[float] = []

    def fake_time() -> float:
        return current_time[0]

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        current_time[0] += seconds

    monkeypatch.setattr(lifecycle.time, "time", fake_time)
    monkeypatch.setattr(lifecycle.time, "monotonic", fake_time)
    monkeypatch.setattr(lifecycle.time, "sleep", fake_sleep)

    calls = 0

    def fake_get_compose_data(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            current_time[0] += 10.0
            return {
                "composeId": "cmp-1",
                "composeStatus": "running",
                "environment": {"projectId": "proj-123"},
                "deployments": [_dep("old-dep", "error")],
            }
        if calls == 2:
            return {
                "composeId": "cmp-1",
                "composeStatus": "running",
                "environment": {"projectId": "proj-123"},
                "deployments": [_dep("old-dep", "error")],
            }
        return {
            "composeId": "cmp-1",
            "composeStatus": "done",
            "environment": {"projectId": "proj-123"},
            "deployments": [_dep("old-dep", "error"), _dep("dep-new", "done")],
        }

    monkeypatch.setattr(lifecycle._dokploy, "get_compose_data", fake_get_compose_data)
    monkeypatch.setattr(
        lifecycle._dokploy, "get_running_deployments_count", lambda *a, **k: 1
    )
    lifecycle.wait_for_dokploy_deployment_rollout(
        _cfg(key="secret-key"),
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
    """AC-testing.preview.15: AC8.13.125: PR preview rollout waits stay bounded when Dokploy is busy."""
    lifecycle = lifecycle_module()
    current_time = [1000.0]

    def fake_time() -> float:
        return current_time[0]

    def fake_sleep(seconds: float) -> None:
        current_time[0] += seconds

    monkeypatch.setattr(lifecycle.time, "time", fake_time)
    monkeypatch.setattr(lifecycle.time, "monotonic", fake_time)
    monkeypatch.setattr(lifecycle.time, "sleep", fake_sleep)
    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_compose_data",
        lambda *a, **k: {
            "composeId": "cmp-1",
            "composeStatus": "running",
            "environment": {"projectId": "proj-123"},
            "deployments": [_dep("old-dep", "running")],
        },
    )
    monkeypatch.setattr(
        lifecycle._dokploy, "get_running_deployments_count", lambda *a, **k: 1
    )

    with pytest.raises(lifecycle.DokployDeploymentDidNotStart):
        lifecycle.wait_for_dokploy_deployment_rollout(
            _cfg(key="secret-key"),
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
    assert 'PYTHONUNBUFFERED: "1"' in workflow
    for s in (
        "timeout-minutes: 25",
        "for i in $(seq 1 60)",
        "stack did not become healthy within 300s",
        "docker compose down --volumes --remove-orphans --timeout 30",
    ):
        assert s in e2e_block


def test_AC7_13_1_no_new_deployment_record_raises_classified_subclass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-testing.preview.16: AC7.13.1: A done compose with no new deployment record fails fast with DokployNoNewDeploymentRecord."""
    lifecycle = lifecycle_module()
    assert issubclass(
        lifecycle.DokployNoNewDeploymentRecord, lifecycle.DokployDeploymentDidNotStart
    )
    monkeypatch.setattr(
        lifecycle._dokploy,
        "get_compose_data",
        lambda *a, **k: {
            "composeStatus": "done",
            "deployments": [{"deploymentId": "old-dep"}],
        },
    )
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)

    with pytest.raises(lifecycle.DokployNoNewDeploymentRecord) as excinfo:
        lifecycle.wait_for_dokploy_deployment_rollout(
            _cfg(),
            compose_id="cmp-1",
            previous_deployment_ids={"old-dep"},
            timeout_seconds=1,
            new_deployment_timeout_seconds=0,
        )

    assert "dokploy-worker-or-deployment-record" in str(excinfo.value)
    out = capsys.readouterr().out
    assert (
        "proceeding to commit-scoped readiness" not in out
        and "did not create a new deployment record" in out
    )


def test_AC7_13_2_env_reconciliation_rejects_stale_non_allowlisted_keys() -> None:
    """AC-testing.preview.17: AC7.13.2: Non-allowlisted stale keys lingering in the effective env are detected."""
    lifecycle = lifecycle_module()
    requested = {"IMAGE_TAG": "pr-1-sha", "ZAI_API_KEY": "wanted"}
    effective = "\n".join(
        ["IMAGE_TAG=pr-1-sha", "ZAI_API_KEY=wanted", "STALE_TOKEN=leaked-secret-value"]
    )
    assert "STALE_TOKEN" in lifecycle.env_reconciliation_divergence(
        requested, effective
    )

    diff = lifecycle.render_env_reconciliation_diff(requested, effective)
    assert (
        "STALE_TOKEN" in diff
        and "leaked-secret-value" not in diff
        and "raw_env_printed: false" in diff
    )
    clean = "\n".join(["IMAGE_TAG=pr-1-sha", "ZAI_API_KEY=wanted"])
    assert lifecycle.env_reconciliation_divergence(requested, clean) == []


def test_AC7_13_3_update_compose_env_fails_fast_on_stale_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.preview.18: AC7.13.3: update_compose_env fails fast when effective remote env keeps a stale key."""
    lifecycle = lifecycle_module()
    requested = lifecycle.build_preview_env(
        pr_number=591,
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        internal_domain="zitian.party",
    )
    effective = lifecycle.render_env(requested) + "ORPHAN_LEFTOVER=stale\n"
    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", lambda *a, **k: "{}")
    monkeypatch.setattr(
        lifecycle._dokploy, "get_compose_env", lambda *a, **k: effective
    )
    with pytest.raises(RuntimeError, match="did not match requested deploy env"):
        lifecycle.update_compose_env(_cfg(), compose_id="cmp-1", env=requested)


def test_AC7_13_4_mutate_then_fail_marks_state_and_records_step(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """AC-testing.preview.19: AC7.13.4: When rollout fails after compose was mutated, deploy_action leaves safe state."""
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

    fake_run = _make_fake_runner(
        None,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
            "compose.create": '{"composeId":"cmp-591-recreated"}',
            "compose.one": {
                "appName": "compose-pr-591-app",
                "env": good_env,
                "composeStatus": "done",
                "deployments": [_dep("old-dep-591")],
            },
        },
    )
    monkeypatch.setattr(lifecycle._dokploy, "update_compose_env", lambda *a, **k: None)
    monkeypatch.setattr(
        lifecycle._dokploy, "update_compose_source", lambda *a, **k: None
    )
    monkeypatch.setattr(lifecycle._util, "run_command", fake_run)

    def fake_wait(*args: object, **kwargs: object) -> None:
        raise lifecycle.DokployDeploymentFailed("rollout never went healthy")

    monkeypatch.setattr(
        lifecycle._dokploy, "wait_for_dokploy_deployment_rollout", fake_wait
    )
    assert lifecycle.main_from_args(_deploy_args()) == 1

    context = json.loads(context_path.read_text())
    assert context["phase"] == "failed"
    assert context.get("mutation_step") in {"deploy", "env", "source", "rollout"}
    assert context.get("recovery_state") in {"rolled-back", "marked-safe-to-reconcile"}
    assert "PR preview deploy failed" in capsys.readouterr().out


def test_AC7_13_4_existing_compose_rolls_back_to_last_known_good_on_env_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """AC7.13.4: An existing compose whose env update fails reconciliation is rolled back to last-known-good."""
    lifecycle = lifecycle_module()
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    context_path = tmp_path / "context.json"
    monkeypatch.setenv(lifecycle.PR_PREVIEW_CONTEXT_ENV, str(context_path))

    last_known_good_env = "IMAGE_TAG=pr-591-prevsha\nGOOD_MARKER=keep\n"
    last_known_good_command = (
        "compose -p compose-pr-591-app -f docker-compose.pr-preview.yml up -d"
    )
    update_calls: list[dict[str, object]] = []

    fake_run = _make_fake_runner(
        None,
        {
            "environment.one": '{"compose":[{"name":"pr-591","composeId":"cmp-591"}]}',
            "compose.one": {
                "appName": "compose-pr-591-app",
                "command": last_known_good_command,
                "env": last_known_good_env,
                "composeStatus": "done",
                "deployments": [_dep("old-dep-591")],
            },
        },
    )
    monkeypatch.setattr(lifecycle._util, "run_command", fake_run)
    monkeypatch.setattr(
        lifecycle._dokploy, "update_compose_source", lambda *a, **k: None
    )

    original_api_call = lifecycle.dokploy_api_call

    def spy_api_call(config, method, endpoint, *, payload=None, expected_status=200):
        if endpoint == "compose.update" and payload is not None:
            update_calls.append(dict(payload))
            return "{}"
        return original_api_call(
            config, method, endpoint, payload=payload, expected_status=expected_status
        )

    monkeypatch.setattr(lifecycle._dokploy, "dokploy_api_call", spy_api_call)

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
    rollback = update_calls[-1]
    assert (
        rollback.get("env") == last_known_good_env
        and rollback.get("command") == last_known_good_command
    )
    assert "Rolled compose back to last-known-good" in capsys.readouterr().out


def test_AC7_13_5_ci_cd_docs_describe_failure_modes() -> None:
    """AC-testing.preview.20: AC7.13.5: ci-cd SSOT documents both the no-new-deployment fail-fast mode and the half-update rollback / safe-to-reconcile recovery path."""
    ci_cd = (ROOT / "common/testing/ci-cd.md").read_text() + (
        ROOT / "common/runtime/ci-cd.md"
    ).read_text()
    assert "dokploy-worker-or-deployment-record" in ci_cd
    assert "safe-to-reconcile" in ci_cd
    lowered = ci_cd.lower()
    assert "no new deployment" in lowered
    assert "rollback" in lowered or "roll back" in lowered
