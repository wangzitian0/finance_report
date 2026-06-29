"""Dokploy API client + compose CRUD + deployment rollout."""

from __future__ import annotations

from tools._lib.dev.pr_preview_lifecycle import _util

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

from tools._lib.dev.pr_preview_lifecycle._base import (
    ALLOWLIST_ENV_KEYS,
    DEPLOYMENT_READY_FOR_READINESS_STATUSES,
    DOKPLOY_API_CONNECT_TIMEOUT_SECONDS,
    DOKPLOY_API_MAX_TIME_SECONDS,
    PR_PREVIEW_COMPOSE_PATH,
    PR_PREVIEW_COMPOSE_TYPE,
    PR_PREVIEW_OWNER,
    PR_PREVIEW_REPOSITORY,
    PR_PREVIEW_SOURCE_TYPE,
)
from tools._lib.dev.pr_preview_lifecycle._preview import preview_compose_command
from tools._lib.dev.pr_preview_lifecycle._util import (
    _safe_message,
    allowlisted_env_matches,
    deployment_ids,
    deployment_signatures,
    dokploy_api_retry_delay_seconds,
    env_reconciliation_divergence,
    latest_new_deployment,
    redact_diagnostic_value,
    render_allowlisted_env_diff,
    render_compose_summary,
    render_env,
    render_env_reconciliation_diff,
)


@dataclass(frozen=True)
class DokployConfig:
    api_url: str
    api_key: str


class DokployDeploymentDidNotStart(RuntimeError):
    """Dokploy accepted a deploy request but did not create a new deployment."""


class DokployNoNewDeploymentRecord(DokployDeploymentDidNotStart):
    """Dokploy never created a new deployment record for the requested rollout.

    Distinct from a generic "did not start": the compose can report
    ``composeStatus=done`` against *stale* deployment records, which previously
    let the waiter false-green and waste the readiness window probing a route
    for a SHA that never rolled out (issue #756). This subclass classifies that
    failure domain (``dokploy-worker-or-deployment-record``) while still being
    caught by the existing ``DokployDeploymentDidNotStart`` retry handlers.
    """


class DokployDeploymentFailed(RuntimeError):
    """Dokploy created a deployment record but the rollout failed."""


class DokployRequestError(RuntimeError):
    """Dokploy API request failed after applying the bounded retry policy."""


def dokploy_api_call(
    config: DokployConfig,
    method: str,
    endpoint: str,
    *,
    payload: dict[str, object] | None = None,
    expected_status: int = 200,
) -> str:
    max_attempts = 4 if method == "GET" else 1
    retry_delay = dokploy_api_retry_delay_seconds()

    for attempt in range(1, max_attempts + 1):
        config_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        data_file: tempfile.NamedTemporaryFile[str] | None = None
        config_path = config_file.name
        data_path = ""
        if "\n" in config.api_key or "\r" in config.api_key:
            config_file.close()
            raise DokployRequestError(
                "Dokploy API key must not contain newline characters "
                "(would corrupt the curl config / allow header injection)"
            )
        escaped_api_key = config.api_key.replace("\\", "\\\\").replace('"', '\\"')
        config_file.write(f'header = "x-api-key: {escaped_api_key}"\n')
        config_file.close()

        cmd = [
            "curl",
            "-sS",
            "--connect-timeout",
            str(DOKPLOY_API_CONNECT_TIMEOUT_SECONDS),
            "--max-time",
            str(DOKPLOY_API_MAX_TIME_SECONDS),
            "--config",
            config_path,
            "-w",
            "\n%{http_code}",
        ]
        try:
            if method == "POST":
                cmd.extend(["-X", "POST", "-H", "Content-Type: application/json"])
                if payload is not None:
                    data_file = tempfile.NamedTemporaryFile(
                        "w", encoding="utf-8", delete=False
                    )
                    data_path = data_file.name
                    json.dump(payload, data_file)
                    data_file.close()
                    cmd.extend(["--data-binary", f"@{data_path}"])
            cmd.append(f"{config.api_url.rstrip('/')}/{endpoint}")

            result = _util.run_command(cmd, check=False)
        finally:
            os.unlink(config_path)
            if data_path:
                os.unlink(data_path)

        body, _, status_text = result.stdout.rpartition("\n")
        try:
            status = int(status_text.strip())
        except ValueError:
            status = expected_status if result.returncode == 0 else 0
            body = result.stdout

        is_transient = (result.returncode == 28) or (status in (500, 502, 503, 504))
        if (
            (result.returncode != 0 or status != expected_status)
            and (attempt < max_attempts)
            and is_transient
        ):
            print(
                f"Dokploy API call failed (attempt {attempt}/{max_attempts}): "
                f"endpoint={endpoint} http_code={status or '000'} "
                f"returncode={result.returncode}. Retrying in {retry_delay}s...",
                file=sys.stderr,
            )
            time.sleep(retry_delay)
            continue

        if result.returncode != 0 or status != expected_status:
            print(f"Dokploy request failed: endpoint={endpoint}", file=sys.stderr)
            print(f"http_code: {status or '000'}", file=sys.stderr)
            print(f"safe_message: {_safe_message(body)}", file=sys.stderr)
            print("raw_body_printed: false", file=sys.stderr)
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
            raise DokployRequestError(f"Dokploy request failed for {endpoint}")
        return body

    raise DokployRequestError(f"Dokploy request failed for {endpoint}")


def find_compose_id_by_name(
    config: DokployConfig, environment_id: str, compose_name: str
) -> str | None:
    body = dokploy_api_call(
        config,
        "GET",
        f"environment.one?environmentId={environment_id}",
    )
    data = json.loads(body or "{}")
    for compose in data.get("compose", []):
        if compose.get("name") == compose_name:
            compose_id = compose.get("composeId")
            return str(compose_id) if compose_id else None
    return None


def create_compose(
    config: DokployConfig,
    *,
    environment_id: str,
    compose_name: str,
    pr_number: int,
    branch: str,
    github_integration_id: str,
) -> str:
    body = dokploy_api_call(
        config,
        "POST",
        "compose.create",
        payload={
            "name": compose_name,
            "description": f"PR #{pr_number}: {compose_name}",
            "environmentId": environment_id,
            "composeType": PR_PREVIEW_COMPOSE_TYPE,
            "sourceType": PR_PREVIEW_SOURCE_TYPE,
            "repository": PR_PREVIEW_REPOSITORY,
            "owner": PR_PREVIEW_OWNER,
            "branch": branch,
            "composePath": PR_PREVIEW_COMPOSE_PATH,
            "githubId": github_integration_id,
            # Placeholder: appName does not exist until Dokploy assigns it during
            # compose.create. update_compose_source() rewrites this with the
            # appName-scoped command before any deploy.
            "command": preview_compose_command(),
            "autoDeploy": False,
        },
    )
    compose_id = json.loads(body or "{}").get("composeId")
    if not compose_id:
        raise RuntimeError("Dokploy compose.create response did not include composeId")
    print(f"Created compose: {compose_id}")
    return str(compose_id)


def get_or_create_compose(
    config: DokployConfig,
    *,
    environment_id: str,
    compose_name: str,
    pr_number: int,
    branch: str,
    github_integration_id: str,
) -> str:
    compose_id = find_compose_id_by_name(config, environment_id, compose_name)
    if compose_id:
        print(f"Found existing compose: {compose_id}")
        return compose_id
    return create_compose(
        config,
        environment_id=environment_id,
        compose_name=compose_name,
        pr_number=pr_number,
        branch=branch,
        github_integration_id=github_integration_id,
    )


def get_or_create_compose_with_status(
    config: DokployConfig,
    *,
    environment_id: str,
    compose_name: str,
    pr_number: int,
    branch: str,
    github_integration_id: str,
) -> tuple[str, bool]:
    compose_id = find_compose_id_by_name(config, environment_id, compose_name)
    if compose_id:
        print(f"Found existing compose: {compose_id}")
        return compose_id, True
    return (
        create_compose(
            config,
            environment_id=environment_id,
            compose_name=compose_name,
            pr_number=pr_number,
            branch=branch,
            github_integration_id=github_integration_id,
        ),
        False,
    )


def update_compose_source(
    config: DokployConfig,
    *,
    compose_id: str,
    branch: str,
    github_integration_id: str,
) -> None:
    # Scope `up` to Dokploy's own appName so compose.delete (which downs the
    # stack by appName) reaps every container. See preview_compose_command().
    app_name = get_compose_app_name(config, compose_id=compose_id)
    dokploy_api_call(
        config,
        "POST",
        "compose.update",
        payload={
            "composeId": compose_id,
            "composeType": PR_PREVIEW_COMPOSE_TYPE,
            "sourceType": PR_PREVIEW_SOURCE_TYPE,
            "repository": PR_PREVIEW_REPOSITORY,
            "owner": PR_PREVIEW_OWNER,
            "branch": branch,
            "composePath": PR_PREVIEW_COMPOSE_PATH,
            "githubId": github_integration_id,
            "command": preview_compose_command(app_name),
            "autoDeploy": False,
        },
    )
    print(f"GitHub preview compose configured for compose: {compose_id}")


def get_compose_data(config: DokployConfig, *, compose_id: str) -> dict[str, object]:
    body = dokploy_api_call(
        config,
        "GET",
        f"compose.one?composeId={compose_id}",
    )
    data = json.loads(body or "{}")
    return data if isinstance(data, dict) else {}


def get_compose_app_name(config: DokployConfig, *, compose_id: str) -> str:
    # Dokploy derives the docker compose project from this appName, and
    # compose.delete downs the stack by it. Fail loud rather than deploy a
    # preview whose teardown cannot reap its containers (the orphan-leak bug).
    app_name = str(get_compose_data(config, compose_id=compose_id).get("appName") or "")
    if not app_name:
        raise RuntimeError(
            f"Dokploy compose {compose_id} has no appName; cannot align the "
            "compose project name with teardown"
        )
    return app_name


def print_compose_summary(
    config: DokployConfig, *, compose_id: str, label: str
) -> None:
    print(
        render_compose_summary(
            get_compose_data(config, compose_id=compose_id), label=label
        )
    )


def get_compose_env(config: DokployConfig, *, compose_id: str) -> str:
    data = get_compose_data(config, compose_id=compose_id)
    env = data.get("env", "")
    return str(env) if env else ""


def update_compose_env(
    config: DokployConfig, *, compose_id: str, env: dict[str, str]
) -> None:
    expected = {key: env[key] for key in ALLOWLIST_ENV_KEYS}
    dokploy_api_call(
        config,
        "POST",
        "compose.update",
        payload={"composeId": compose_id, "env": render_env(env)},
    )
    effective_env = get_compose_env(config, compose_id=compose_id)
    print(render_allowlisted_env_diff(expected, effective_env))
    # Reconcile the *whole* requested env against the effective remote env so a
    # stale non-allowlisted key from a prior deploy cannot silently diverge
    # (issue #758). Diagnostics name keys only and never print values.
    print(render_env_reconciliation_diff(env, effective_env))
    if not allowlisted_env_matches(expected, effective_env):
        raise RuntimeError(
            "Dokploy effective environment did not match requested deploy env"
        )
    if env_reconciliation_divergence(env, effective_env):
        raise RuntimeError(
            "Dokploy effective environment did not match requested deploy env "
            "after full reconciliation (stale or divergent non-allowlisted keys)"
        )
    print(f"Environment variables configured for compose: {compose_id}")


def capture_compose_state(config: DokployConfig, *, compose_id: str) -> dict[str, str]:
    """Snapshot the last-known-good compose source command and env.

    Captured *before* a deploy mutates the compose so the failure path can roll
    the record back instead of leaving a half-updated compose pointing at a SHA
    that never rolled out (issue #758).
    """

    data = get_compose_data(config, compose_id=compose_id)
    return {
        "command": str(data.get("command") or ""),
        "env": str(data.get("env") or ""),
    }


def restore_compose_state(
    config: DokployConfig, *, compose_id: str, state: dict[str, str]
) -> None:
    """Roll the compose source command and env back to a captured snapshot."""

    payload: dict[str, object] = {"composeId": compose_id}
    if state.get("command"):
        payload["command"] = state["command"]
    payload["env"] = state.get("env", "")
    dokploy_api_call(config, "POST", "compose.update", payload=payload)
    print(f"Rolled compose back to last-known-good source/env: {compose_id}")


def configure_preview_compose(
    config: DokployConfig,
    *,
    compose_id: str,
    args: argparse.Namespace,
    preview_env: dict[str, str],
    on_step: Callable[[str], None] | None = None,
) -> None:
    # ``on_step`` lets the caller mark which mutation the compose was left at
    # (source vs env) so a failure can report and recover precisely (issue #758).
    if on_step is not None:
        on_step("source")
    update_compose_source(
        config,
        compose_id=compose_id,
        branch=args.branch,
        github_integration_id=args.github_integration_id,
    )
    print_compose_summary(config, compose_id=compose_id, label="after-source-update")
    if on_step is not None:
        on_step("env")
    update_compose_env(
        config,
        compose_id=compose_id,
        env=preview_env,
    )
    print_compose_summary(config, compose_id=compose_id, label="after-env-update")


def deploy_compose(
    config: DokployConfig, *, compose_id: str, force_redeploy: bool = False
) -> None:
    endpoint = "compose.redeploy" if force_redeploy else "compose.deploy"
    body = dokploy_api_call(
        config,
        "POST",
        endpoint,
        payload={"composeId": compose_id},
    )
    action = "Redeployment" if force_redeploy else "Deployment"
    print(f"{action} triggered for compose: {compose_id}")
    print(f"dokploy_queue_message: {_safe_message(body)}")


def deploy_compose_and_wait_for_rollout(
    config: DokployConfig,
    *,
    compose_id: str,
    force_redeploy: bool,
) -> None:
    compose_data = get_compose_data(config, compose_id=compose_id)
    previous_deployment_ids = deployment_ids(compose_data.get("deployments"))
    previous_deployment_signatures = deployment_signatures(
        compose_data.get("deployments")
    )
    deploy_compose(config, compose_id=compose_id, force_redeploy=force_redeploy)
    print_compose_summary(config, compose_id=compose_id, label="after-deploy-trigger")
    wait_for_dokploy_deployment_rollout(
        config,
        compose_id=compose_id,
        previous_deployment_ids=previous_deployment_ids,
        previous_deployment_signatures=previous_deployment_signatures,
    )


def fail_before_readiness_after_missing_record(
    *,
    compose_id: str,
    error: DokployDeploymentDidNotStart,
) -> None:
    print(
        "Dokploy deployment record was not created after the deploy request, "
        "so readiness will not start. "
        "platform_failure_domain=dokploy-control-plane-record-missing "
        f"compose_id={compose_id} reason={redact_diagnostic_value(error)}"
    )
    print("raw_compose_printed: false")
    print("raw_deployment_printed: false")


def get_running_deployments_count(config: DokployConfig, project_id: str) -> int:
    try:
        body = dokploy_api_call(config, "GET", f"project.one?projectId={project_id}")
        data = json.loads(body or "{}")
        running_count = 0
        for env in data.get("environments", []):
            for comp in env.get("compose", []):
                if comp.get("composeStatus") in ("running", "deploying"):
                    running_count += 1
        return running_count
    except Exception as exc:
        print(f"Warning: Failed to check project deployment status: {exc}")
    return 0


def wait_for_dokploy_deployment_rollout(
    config: DokployConfig,
    *,
    compose_id: str,
    previous_deployment_ids: set[str] | None = None,
    previous_deployment_signatures: dict[str, tuple[str, str, str, str]] | None = None,
    timeout_seconds: int = 900,
    new_deployment_timeout_seconds: int = 600,
    interval_seconds: int = 5,
) -> None:
    previous_deployment_ids = previous_deployment_ids or set()
    previous_deployment_signatures = previous_deployment_signatures or {}
    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    new_deployment_deadline = started_at + min(
        timeout_seconds,
        new_deployment_timeout_seconds,
    )
    attempt = 0
    while True:
        attempt += 1
        now = time.monotonic()
        try:
            data = get_compose_data(config, compose_id=compose_id)
        except DokployRequestError as exc:
            if now >= deadline:
                raise
            print(
                "Dokploy rollout probe API failure: "
                f"attempt={attempt} compose_id={compose_id} "
                f"error={redact_diagnostic_value(exc)}"
            )
            time.sleep(interval_seconds)
            continue
        compose_status = str(data.get("composeStatus") or "")
        deployments = data.get("deployments")
        deployment_count = len(deployments) if isinstance(deployments, list) else 0
        current_ids = deployment_ids(deployments)
        new_deployment_ids = sorted(current_ids - previous_deployment_ids)
        current_deployment_signatures = deployment_signatures(deployments)
        existing_deployment_updates = sorted(
            deployment_id
            for deployment_id in previous_deployment_ids
            if (
                deployment_id in current_deployment_signatures
                and deployment_id in previous_deployment_signatures
                and current_deployment_signatures[deployment_id]
                != previous_deployment_signatures[deployment_id]
            )
        )
        if attempt == 1 or attempt % 6 == 0 or compose_status != "idle":
            print(
                render_compose_summary(
                    data, label=f"deployment-rollout-attempt-{attempt}"
                )
            )
        if compose_status == "error":
            print(
                render_compose_summary(data, label=f"compose-error-attempt-{attempt}")
            )
            if new_deployment_ids:
                latest = (
                    latest_new_deployment(deployments, set(new_deployment_ids)) or {}
                )
                latest_id = str(latest.get("deploymentId") or new_deployment_ids[-1])
                raise DokployDeploymentFailed(
                    "Dokploy compose entered error status before readiness polling: "
                    f"compose_id={compose_id} deployment_id={latest_id}"
                )
            print(
                "Dokploy compose still reports a stale error before the queued "
                "redeploy has created a new deployment record; continuing rollout poll."
            )
        print(
            f"Dokploy rollout probe: attempt={attempt} "
            f"compose_id={compose_id} "
            f"composeStatus={compose_status or 'unknown'} "
            f"deployment_count={deployment_count} "
            f"new_deployment_ids={','.join(new_deployment_ids) or 'none'}"
        )
        if (
            not new_deployment_ids
            and existing_deployment_updates
            and compose_status in DEPLOYMENT_READY_FOR_READINESS_STATUSES
        ):
            existing_latest = (
                latest_new_deployment(deployments, set(existing_deployment_updates))
                or {}
            )
            existing_latest_id = str(
                existing_latest.get("deploymentId") or existing_deployment_updates[-1]
            )
            existing_latest_status = str(existing_latest.get("status") or "unknown")
            print(
                "Dokploy rollout observed as existing deployment record update: "
                f"compose_id={compose_id} "
                f"existing_deployment_ids={','.join(existing_deployment_updates)} "
                f"latest_deployment_id={existing_latest_id} "
                f"latest_deployment_status={existing_latest_status}"
            )
            if existing_latest_status == "error":
                print(
                    render_compose_summary(
                        data,
                        label=f"existing-deployment-error-attempt-{attempt}",
                    )
                )
                raise DokployDeploymentFailed(
                    "Dokploy deployment failed before readiness polling: "
                    f"compose_id={compose_id} deployment_id={existing_latest_id}"
                )
            if existing_latest_status in DEPLOYMENT_READY_FOR_READINESS_STATUSES:
                return
        if new_deployment_ids:
            latest = latest_new_deployment(deployments, set(new_deployment_ids)) or {}
            latest_id = str(latest.get("deploymentId") or new_deployment_ids[-1])
            latest_status = str(latest.get("status") or "unknown")
            if latest_status == "error":
                print(
                    render_compose_summary(
                        data,
                        label=f"deployment-error-attempt-{attempt}",
                    )
                )
                raise DokployDeploymentFailed(
                    "Dokploy deployment failed before readiness polling: "
                    f"compose_id={compose_id} deployment_id={latest_id}"
                )
            print(
                f"Dokploy deployment observed: compose_id={compose_id} "
                f"composeStatus={compose_status or 'unknown'} "
                f"deployment_count={deployment_count} "
                f"new_deployment_ids={','.join(new_deployment_ids)} "
                f"latest_deployment_id={latest_id} "
                f"latest_deployment_status={latest_status}"
            )
            if latest_status in DEPLOYMENT_READY_FOR_READINESS_STATUSES:
                return
        if (
            not new_deployment_ids
            and current_ids
            and compose_status in DEPLOYMENT_READY_FOR_READINESS_STATUSES
            and now >= new_deployment_deadline
        ):
            print(
                "Dokploy did not create a new deployment record, but compose "
                "is done with existing deployment records; failing before "
                "application readiness instead of probing the route for a SHA "
                "that never rolled out. platform_failure_domain="
                "dokploy-worker-or-deployment-record"
            )
            raise DokployNoNewDeploymentRecord(
                "Dokploy compose is done with existing deployment records but "
                "did not create a new deployment record for this rollout before "
                f"readiness polling: compose_id={compose_id} "
                f"composeStatus={compose_status or 'unknown'} "
                f"deployment_count={deployment_count} "
                "platform_failure_domain=dokploy-worker-or-deployment-record"
            )
        if not new_deployment_ids and now >= new_deployment_deadline:
            project_id = (
                data.get("environment", {}).get("projectId")
                if isinstance(data, dict)
                else None
            )
            if (
                project_id
                and get_running_deployments_count(config, project_id) > 0
                and now < deadline
            ):
                print(
                    "Warning: Dokploy is currently busy with other deployments. "
                    "Extending the new deployment timeout deadline."
                )
                new_deployment_deadline = min(now + 60.0, deadline)
                continue
            raise DokployNoNewDeploymentRecord(
                "Dokploy deployment did not create a new deployment before "
                f"readiness polling: compose_id={compose_id} "
                f"composeStatus={compose_status or 'unknown'} "
                f"deployment_count={deployment_count} "
                "platform_failure_domain=dokploy-worker-or-deployment-record"
            )
        if now >= deadline:
            raise RuntimeError(
                "Dokploy deployment did not reach done before readiness "
                f"polling: compose_id={compose_id} composeStatus={compose_status or 'unknown'} "
                f"deployment_count={deployment_count} "
                f"new_deployment_ids={','.join(new_deployment_ids)}"
            )
        time.sleep(interval_seconds)


def delete_compose(config: DokployConfig, *, compose_id: str) -> None:
    dokploy_api_call(
        config,
        "POST",
        "compose.delete",
        payload={"composeId": compose_id},
    )
    print(f"Compose deleted: {compose_id}")
