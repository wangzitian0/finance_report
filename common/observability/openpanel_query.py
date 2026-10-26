#!/usr/bin/env python3
"""Thin OpenPanel query CLI for inspecting frontend product-analytics data.

Delegates OpenPanel export API URL validation, API key resolution, declarative
funnel preset loading, payload construction, Markdown summary rendering, and
HTTP transport to :mod:`infra2_sdk.observability` (#2544).
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import sys
import urllib.error

from infra2_sdk.observability import (
    build_openpanel_payload,
    format_openpanel_markdown,
    load_openpanel_funnel_presets,
    post_openpanel_json,
    resolve_openpanel_api_key,
    resolve_openpanel_api_url,
)

DEFAULT_API_URL = "https://openpanel.zitian.party/api"
API_URL_ENV = "OPENPANEL_API_URL"
OPENPANEL_CONTRACT_PATH = (
    Path(__file__).resolve().parent / "data" / "openpanel_analytics.json"
)
FUNNEL_PRESETS: dict[str, tuple[str, ...]] = load_openpanel_funnel_presets(
    OPENPANEL_CONTRACT_PATH
)


def resolve_api_url(explicit: str | None) -> str:
    """Resolve and validate the API base URL via ``infra2_sdk.observability``."""
    return resolve_openpanel_api_url(explicit, default_url=DEFAULT_API_URL)


def resolve_api_key(env: Mapping[str, str] | None = None) -> str:
    """Return the API key from the environment via ``infra2_sdk.observability``."""
    return resolve_openpanel_api_key(env)


def resolve_funnel_steps(args: argparse.Namespace) -> list[str]:
    """Resolve funnel steps from ``--preset`` or ``--steps``."""
    preset = getattr(args, "preset", None)
    raw_steps = getattr(args, "steps", None)
    if preset:
        if preset not in FUNNEL_PRESETS:
            raise SystemExit(f"error: unknown funnel preset {preset!r}")
        return list(FUNNEL_PRESETS[preset])
    steps = [stripped for s in (raw_steps or "").split(",") if (stripped := s.strip())]
    if len(steps) < 2:
        raise SystemExit(
            "error: funnel requires at least 2 steps via --steps or --preset."
        )
    return steps


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    """Build the JSON request body for the selected subcommand."""
    steps = resolve_funnel_steps(args) if args.command == "funnel" else None
    return build_openpanel_payload(
        command=args.command,
        limit=args.limit,
        env=args.env,
        event=getattr(args, "event", None),
        steps=steps,
    )


def format_markdown_summary(
    result: Mapping[str, object], *, command: str, env: str | None = None
) -> str:
    """Format an OpenPanel events or funnel response as a Markdown summary table."""
    return format_openpanel_markdown(result, command=command, env=env)


def post_json(
    url: str, api_key: str, payload: dict[str, object]
) -> dict[str, object]:  # pragma: no cover - real network egress, injected in tests
    """POST a JSON payload and return the decoded response."""
    return post_openpanel_json(url, api_key, payload)


def run(args: argparse.Namespace, *, transport=None) -> dict[str, object]:
    """Resolve config, build the payload, and execute the request."""
    if transport is None:
        transport = post_json
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
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    events = sub.add_parser("events", help="List captured events.")
    events.add_argument(
        "--event", default=None, help="Event name to filter on (default: all events)."
    )

    funnel = sub.add_parser("funnel", help="Compute a conversion funnel.")
    funnel.add_argument(
        "--steps",
        default=None,
        help="Comma-separated ordered event names making up the funnel.",
    )
    funnel.add_argument(
        "--preset",
        choices=tuple(FUNNEL_PRESETS),
        default=None,
        help="Named funnel preset (e.g. core-funnel or activation).",
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
    if getattr(args, "format", "json") == "markdown":
        sys.stdout.write(
            format_markdown_summary(result, command=args.command, env=args.env) + "\n"
        )
    else:
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
