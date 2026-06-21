"""Pure helpers: command run, env parse/render/diff, deployment selection."""

from __future__ import annotations

import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

from tools._lib.dev.pr_preview_lifecycle._base import (
    ALLOWLIST_ENV_KEYS,
    AUTH_VALUE_PATTERN,
    COMPOSE_SUMMARY_KEYS,
    DEPLOYMENT_DIAGNOSTIC_KEYS,
    SENSITIVE_ASSIGNMENT_PATTERN,
    VAULT_TOKEN_PATTERN,
    is_platform_managed_env_key,
)


def run_command(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def parse_positive_int_env(var_name: str, default: int) -> int:
    """Return a positive integer from env, otherwise fallback to default."""

    value = os.environ.get(var_name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        print(
            f"Invalid value for {var_name}; expected integer. "
            f"falling back to {default}."
        )
        return default
    if parsed <= 0:
        print(
            f"Invalid value for {var_name}; expected positive integer. "
            f"falling back to {default}."
        )
        return default
    return parsed


def parse_env(env_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def render_env(env: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in env.items()) + "\n"


def allowlisted_env_matches(expected: dict[str, str], actual_env_text: str) -> bool:
    actual = parse_env(actual_env_text)
    return all(
        expected.get(key, "") == actual.get(key, "") for key in ALLOWLIST_ENV_KEYS
    )


def render_allowlisted_env_diff(expected: dict[str, str], actual_env_text: str) -> str:
    actual = parse_env(actual_env_text)
    lines = ["Effective deploy env diff"]
    for key in ALLOWLIST_ENV_KEYS:
        expected_value = expected.get(key, "")
        actual_value = actual.get(key, "")
        if expected_value == actual_value:
            lines.append(f"{key}: match")
        else:
            lines.append(f"{key}: expected={expected_value} actual={actual_value}")
    lines.append(
        f"result: {'match' if allowlisted_env_matches(expected, actual_env_text) else 'mismatch'}"
    )
    lines.append("raw_env_printed: false")
    return "\n".join(lines)


def env_reconciliation_divergence(
    requested: dict[str, str], actual_env_text: str
) -> list[str]:
    """Return env keys whose effective remote value diverges from the request.

    Covers the whole requested env (not just the allowlist) plus stale keys that
    linger in the effective env but were never requested — the non-allowlisted
    drift class from issue #758. Only key *names* are returned so callers can
    surface them without leaking secret values.
    """

    actual = parse_env(actual_env_text)
    divergent: set[str] = set()
    # A requested key that the effective env *does* expose must match. We do not
    # flag requested keys the effective payload omits: Dokploy can return a
    # partial view, and "incomplete echo" is a separate concern from the stale
    # non-allowlisted drift this guards against.
    for key, value in requested.items():
        if key in actual and actual[key] != value:
            divergent.add(key)
    # A key present in the effective env that we never requested and that the
    # platform does not own is a stale leftover from a prior deploy.
    for key in actual:
        if key not in requested and not is_platform_managed_env_key(key):
            divergent.add(key)
    return sorted(divergent)


def render_env_reconciliation_diff(
    requested: dict[str, str], actual_env_text: str
) -> str:
    """Render a secret-safe reconciliation diagnostic (key names only)."""

    divergent = env_reconciliation_divergence(requested, actual_env_text)
    actual = parse_env(actual_env_text)
    lines = ["Effective deploy env reconciliation"]
    lines.append(f"requested_key_count: {len(requested)}")
    lines.append(f"effective_key_count: {len(actual)}")
    for key in divergent:
        # env_reconciliation_divergence only reports keys that are present in the
        # effective env: either a stale key we never requested, or a requested
        # key whose effective value differs. It deliberately does not flag keys
        # absent from the effective env, so those two are the only reasons here.
        reason = "stale-unrequested-key" if key not in requested else "value-mismatch"
        lines.append(f"divergent_key: {key} ({reason})")
    lines.append(f"result: {'match' if not divergent else 'mismatch'}")
    lines.append("raw_env_printed: false")
    return "\n".join(lines)


def redact_diagnostic_value(value: object) -> str:
    rendered = str(value)
    rendered = AUTH_VALUE_PATTERN.sub(r"\1 <redacted>", rendered)
    rendered = SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1<redacted>", rendered)
    rendered = VAULT_TOKEN_PATTERN.sub("hvs.<redacted>", rendered)
    return rendered[:300]


def render_deployment_diagnostics(deployment: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for key in DEPLOYMENT_DIAGNOSTIC_KEYS:
        value = deployment.get(key)
        if isinstance(value, str) and value:
            lines.append(f"latest_deployment_{key}: {redact_diagnostic_value(value)}")
    return lines


def render_compose_summary(data: dict[str, object], *, label: str) -> str:
    lines = [f"Dokploy compose summary ({label})"]
    for key in COMPOSE_SUMMARY_KEYS:
        value = data.get(key)
        if value is None or value == "":
            continue
        lines.append(f"{key}: {str(value)[:160]}")
    lines.append(f"env_present: {bool(data.get('env'))}")
    deployments = data.get("deployments")
    if isinstance(deployments, list):
        lines.append(f"deployment_count: {len(deployments)}")
        latest = latest_deployment(deployments)
        if latest:
            for key in (
                "deploymentId",
                "status",
                "createdAt",
                "startedAt",
                "finishedAt",
            ):
                value = latest.get(key)
                if value:
                    lines.append(f"latest_deployment_{key}: {str(value)[:160]}")
            lines.extend(render_deployment_diagnostics(latest))
    lines.append("raw_compose_printed: false")
    lines.append("raw_deployment_printed: false")
    return "\n".join(lines)


def _deployment_timestamp(deployment: dict[str, object]) -> str:
    for key in ("createdAt", "startedAt", "finishedAt"):
        value = deployment.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def latest_deployment(deployments: object) -> dict[str, object] | None:
    if not isinstance(deployments, list):
        return None
    deployment_dicts = [
        deployment for deployment in deployments if isinstance(deployment, dict)
    ]
    if not deployment_dicts:
        return None
    return max(deployment_dicts, key=_deployment_timestamp)


def deployment_ids(deployments: object) -> set[str]:
    if not isinstance(deployments, list):
        return set()
    ids: set[str] = set()
    for deployment in deployments:
        if not isinstance(deployment, dict):
            continue
        deployment_id = deployment.get("deploymentId")
        if deployment_id:
            ids.add(str(deployment_id))
    return ids


def deployment_signatures(deployments: object) -> dict[str, tuple[str, str, str, str]]:
    """Capture fields that change when a deployment record is actively updated."""

    if not isinstance(deployments, list):
        return {}
    signatures: dict[str, tuple[str, str, str, str]] = {}
    for deployment in deployments:
        if not isinstance(deployment, dict):
            continue
        deployment_id = deployment.get("deploymentId")
        if deployment_id:
            signatures[str(deployment_id)] = (
                str(deployment.get("status") or ""),
                str(deployment.get("createdAt") or ""),
                str(deployment.get("startedAt") or ""),
                str(deployment.get("finishedAt") or ""),
            )
    return signatures


def latest_new_deployment(
    deployments: object, new_deployment_ids: set[str]
) -> dict[str, object] | None:
    if not isinstance(deployments, list):
        return None
    candidates = [
        deployment
        for deployment in deployments
        if isinstance(deployment, dict)
        and str(deployment.get("deploymentId") or "") in new_deployment_ids
    ]
    return latest_deployment(candidates)


def _safe_message(body: str) -> str:
    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError:
        return "unavailable"
    for key in ("message", "error", "status"):
        value = parsed.get(key)
        if isinstance(value, str) and value:
            return value[:160]
    return "unavailable"


def dokploy_api_retry_delay_seconds() -> float:
    raw_value = os.environ.get("DOKPLOY_API_RETRY_DELAY_SECONDS", "2.0")
    try:
        retry_delay = float(raw_value)
    except ValueError:
        return 2.0
    return retry_delay if retry_delay >= 0 else 2.0


def normalize_dash_prefixed_values(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    index = 0
    value_options = {"--environment-id"}
    while index < len(argv):
        current = argv[index]
        if current in value_options and index + 1 < len(argv):
            normalized.append(f"{current}={argv[index + 1]}")
            index += 2
            continue
        normalized.append(current)
        index += 1
    return normalized
