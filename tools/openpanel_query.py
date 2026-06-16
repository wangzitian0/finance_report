#!/usr/bin/env python3
"""Thin OpenPanel query CLI for inspecting frontend product-analytics data.

A dependency-light (stdlib-only) wrapper over the OpenPanel export API, used to
pull events / funnels when triaging frontend issues. The API key is read from
the ``OPENPANEL_API_KEY`` environment variable and never accepted as a CLI
argument (so it cannot leak into shell history / process listings).

Examples::

    OPENPANEL_API_KEY=... python openpanel_query.py events --env staging
    OPENPANEL_API_KEY=... python openpanel_query.py funnel \\
        --steps screen_view,upload_clicked --env production

The default API base mirrors the self-hosted instance used by
``components/Analytics.tsx`` (``https://openpanel.zitian.party/api``); override
with ``--api-url`` or ``OPENPANEL_API_URL`` for other environments.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Sequence

DEFAULT_API_URL = "https://openpanel.zitian.party/api"
API_KEY_ENV = "OPENPANEL_API_KEY"
API_URL_ENV = "OPENPANEL_API_URL"


def resolve_api_url(explicit: str | None) -> str:
    """Resolve the API base URL: CLI flag > env var > self-hosted default."""
    candidate = (explicit or os.environ.get(API_URL_ENV) or "").strip()
    return candidate or DEFAULT_API_URL


def resolve_api_key(env: dict[str, str] | None = None) -> str:
    """Return the API key from the environment or exit with a clear error."""
    source = env if env is not None else dict(os.environ)
    key = (source.get(API_KEY_ENV) or "").strip()
    if not key:
        raise SystemExit(
            f"error: {API_KEY_ENV} is not set; export it before querying OpenPanel."
        )
    return key


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    """Build the JSON request body for the selected subcommand.

    Pure (no I/O) so it is exhaustively unit-testable.
    """
    payload: dict[str, object] = {"limit": args.limit}
    if args.env:
        # OpenPanel events are tagged with `environment` global property by
        # `components/Analytics.tsx`; filter on it so per-env data is isolable.
        payload["filters"] = [
            {"name": "environment", "operator": "is", "value": [args.env]}
        ]
    if args.command == "events":
        payload["event"] = args.event or "*"
    elif args.command == "funnel":
        payload["steps"] = [
            stripped for s in (args.steps or "").split(",") if (stripped := s.strip())
        ]
    return payload


def post_json(url: str, api_key: str, payload: dict[str, object]) -> dict[str, object]:
    """POST a JSON payload and return the decoded response.

    Isolated so tests can monkeypatch it without making a network call.
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - fixed https base, not user-controlled scheme
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "openpanel-client-secret": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def run(args: argparse.Namespace, *, transport=post_json) -> dict[str, object]:
    """Resolve config, build the payload, and execute the request.

    ``transport`` is injectable for tests.
    """
    api_url = resolve_api_url(args.api_url)
    api_key = resolve_api_key()
    endpoint = f"{api_url.rstrip('/')}/{args.command}"
    payload = build_payload(args)
    return transport(endpoint, api_key, payload)


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser (shared by ``main`` and ``--help`` smoke)."""
    parser = argparse.ArgumentParser(
        prog="openpanel_query",
        description="Query OpenPanel frontend analytics (events / funnels).",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help=f"OpenPanel API base URL (default: {API_URL_ENV} env or {DEFAULT_API_URL}).",
    )
    parser.add_argument(
        "--env",
        default=None,
        help="Filter results to a single environment (e.g. staging, production).",
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Maximum rows to return (default: 100)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    events = sub.add_parser("events", help="List captured events.")
    events.add_argument(
        "--event", default=None, help="Event name to filter on (default: all events)."
    )

    funnel = sub.add_parser("funnel", help="Compute a conversion funnel.")
    funnel.add_argument(
        "--steps",
        required=True,
        help="Comma-separated ordered event names making up the funnel.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except urllib.error.URLError as exc:  # pragma: no cover - network failure path
        print(f"error: OpenPanel request failed: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
