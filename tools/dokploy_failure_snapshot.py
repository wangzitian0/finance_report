#!/usr/bin/env python3
"""Emit a platform-failure snapshot for a Dokploy compose on deploy failure.

Part of issue #768: when a PR-preview / staging deploy or readiness gate fails,
the pipeline should surface the platform-layer state (Dokploy compose status,
latest deployment status/error, whether a new deployment record was ever
created) so triage can separate a platform failure from an application failure
without SSHing to the host.

Reads only the Dokploy API (no SSH), so it runs from any CI job that already
holds DOKPLOY_API_KEY. Stdlib-only and never fails the calling job: diagnostic
output goes to stdout; exit code is always 0.

Usage:
  python tools/dokploy_failure_snapshot.py \
    --compose-id "$COMPOSE_ID" --api-url "$DOKPLOY_API_URL"
  (DOKPLOY_API_KEY is read from the environment.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Compose/deployment states Dokploy reports once a rollout has actually started.
_ACTIVE_STATES = {"running", "done", "success", "successful"}
_PLATFORM_HEALTH_FIELDS = (
    "target_container_status",
    "target_container_restart_count",
    "host_load_1m",
    "host_memory_used_pct",
    "vault_agent_error_loop",
)


def _api_get(api_url: str, api_key: str, path: str) -> dict:
    url = f"{api_url.rstrip('/')}/{path}"
    req = urllib.request.Request(
        url,
        headers={
            "x-api-key": api_key,
            "Accept": "application/json",
            # A non-default User-Agent avoids Cloudflare bot blocking (error 1010).
            "User-Agent": "finance-report-pipeline-snapshot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed internal API host
        return json.loads(resp.read().decode("utf-8"))


def _classify(compose_status: str, deployments: list[dict]) -> str:
    """Classify the platform failure domain from Dokploy state."""
    latest_status = ""
    if deployments:
        latest = sorted(
            deployments, key=lambda d: str(d.get("startedAt") or ""), reverse=True
        )[0]
        latest_status = str(latest.get("status") or "").lower()

    if compose_status == "error" or latest_status == "error":
        return "dokploy-deployment-error"
    if not deployments or compose_status in {"idle", ""}:
        return "dokploy-worker-or-deployment-record"
    if compose_status in _ACTIVE_STATES and latest_status in _ACTIVE_STATES:
        return "platform-ok-check-application-or-route"
    return "dokploy-rollout-incomplete"


def build_signoz_query_links(
    *,
    signoz_url: str,
    service_name: str,
    deployment_environment: str,
    service_version: str,
    github_run_id: str,
) -> dict[str, str]:
    """Build stable SigNoz pivot links for the deployed version/run."""
    base = signoz_url.rstrip("/")
    filters = {
        "service.name": service_name,
        "deployment.environment": deployment_environment,
        "service.version": service_version,
        "github.run_id": github_run_id,
    }
    encoded = urllib.parse.urlencode(filters)
    return {
        "signoz_logs_query_url": f"{base}/logs?{encoded}",
        "signoz_traces_query_url": f"{base}/traces?{encoded}",
    }


def load_platform_health(raw_json: str | None) -> dict[str, object]:
    """Return only the non-secret platform health fields the deploy summary needs."""
    if not raw_json:
        return {}
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return {"platform_health_error": "invalid-json"}
    if not isinstance(payload, dict):
        return {"platform_health_error": "not-an-object"}
    return {key: payload[key] for key in _PLATFORM_HEALTH_FIELDS if key in payload}


def build_snapshot(
    api_url: str,
    api_key: str,
    compose_id: str,
    *,
    platform_health: dict[str, object] | None = None,
    signoz_links: dict[str, str] | None = None,
) -> dict:
    try:
        data = _api_get(api_url, api_key, f"compose.one?composeId={compose_id}")
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        return {
            "compose_id": compose_id,
            "error": f"could not read Dokploy compose: {type(exc).__name__}",
            "platform_failure_domain": "dokploy-api-unreachable",
            **(platform_health or {}),
            **(signoz_links or {}),
        }

    deployments = [d for d in (data.get("deployments") or []) if isinstance(d, dict)]
    compose_status = str(data.get("composeStatus") or "unknown")
    latest = (
        sorted(deployments, key=lambda d: str(d.get("startedAt") or ""), reverse=True)[
            0
        ]
        if deployments
        else {}
    )
    return {
        "compose_id": compose_id,
        "compose_status": compose_status,
        "deployment_count": len(deployments),
        "latest_deployment_status": str(latest.get("status") or "none"),
        "latest_deployment_title": str(latest.get("title") or ""),
        "latest_deployment_error": str(latest.get("errorMessage") or "")[:500],
        "platform_failure_domain": _classify(compose_status, deployments),
        **(platform_health or {}),
        **(signoz_links or {}),
    }


def render_markdown(snapshot: dict) -> str:
    lines = [
        "### Platform failure snapshot (Dokploy)",
        "",
        "| field | value |",
        "|---|---|",
    ]
    for key in (
        "compose_id",
        "compose_status",
        "deployment_count",
        "latest_deployment_status",
        "latest_deployment_title",
        "latest_deployment_error",
        "platform_failure_domain",
        "target_container_status",
        "target_container_restart_count",
        "host_load_1m",
        "host_memory_used_pct",
        "vault_agent_error_loop",
        "signoz_logs_query_url",
        "signoz_traces_query_url",
        "error",
        "platform_health_error",
    ):
        if key in snapshot and snapshot[key] != "":
            lines.append(f"| {key} | {snapshot[key]} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-id", required=True)
    parser.add_argument("--api-url", default=os.getenv("DOKPLOY_API_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("DOKPLOY_API_KEY", ""))
    parser.add_argument("--platform-health-json", default="")
    parser.add_argument("--signoz-url", default="")
    parser.add_argument("--service-name", default="finance-report-backend")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--service-version", default="")
    parser.add_argument("--github-run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument(
        "--markdown", action="store_true", help="Also print a Markdown table"
    )
    args = parser.parse_args(argv)
    platform_health = load_platform_health(args.platform_health_json)
    signoz_links = (
        build_signoz_query_links(
            signoz_url=args.signoz_url,
            service_name=args.service_name,
            deployment_environment=args.deployment_environment,
            service_version=args.service_version,
            github_run_id=args.github_run_id,
        )
        if args.signoz_url
        and args.deployment_environment
        and args.service_version
        and args.github_run_id
        else {}
    )

    if not args.compose_id or not args.api_url or not args.api_key:
        # Missing inputs must not fail the calling job; emit a clear marker.
        print(
            json.dumps(
                {
                    "platform_failure_domain": "snapshot-skipped-missing-inputs",
                    "compose_id": args.compose_id or "",
                    **platform_health,
                    **signoz_links,
                }
            )
        )
        return 0

    snapshot = build_snapshot(
        args.api_url,
        args.api_key,
        args.compose_id,
        platform_health=platform_health,
        signoz_links=signoz_links,
    )
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    if args.markdown:
        print(render_markdown(snapshot))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
