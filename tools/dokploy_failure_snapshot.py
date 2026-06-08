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
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Compose/deployment states Dokploy reports once a rollout has actually started.
_ACTIVE_STATES = {"running", "done", "success", "successful"}


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


def build_snapshot(api_url: str, api_key: str, compose_id: str) -> dict:
    try:
        data = _api_get(api_url, api_key, f"compose.one?composeId={compose_id}")
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        return {
            "compose_id": compose_id,
            "error": f"could not read Dokploy compose: {type(exc).__name__}",
            "platform_failure_domain": "dokploy-api-unreachable",
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
        "error",
    ):
        if key in snapshot and snapshot[key] != "":
            lines.append(f"| {key} | {snapshot[key]} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-id", required=True)
    parser.add_argument("--api-url", default=os.getenv("DOKPLOY_API_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("DOKPLOY_API_KEY", ""))
    parser.add_argument(
        "--markdown", action="store_true", help="Also print a Markdown table"
    )
    args = parser.parse_args(argv)

    if not args.compose_id or not args.api_url or not args.api_key:
        # Missing inputs must not fail the calling job; emit a clear marker.
        print(
            json.dumps(
                {
                    "platform_failure_domain": "snapshot-skipped-missing-inputs",
                    "compose_id": args.compose_id or "",
                }
            )
        )
        return 0

    snapshot = build_snapshot(args.api_url, args.api_key, args.compose_id)
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    if args.markdown:
        print(render_markdown(snapshot))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
