#!/usr/bin/env python3
"""Thin OpenPanel query CLI for inspecting frontend product-analytics data.

A dependency-light (stdlib-only) wrapper over the OpenPanel export API, used to
pull events / funnels when triaging frontend issues. The API key is read from
the ``OPENPANEL_API_KEY`` environment variable and never accepted as a CLI
argument (so it cannot leak into shell history / process listings).

Examples::

    OPENPANEL_API_KEY=... python openpanel_query.py events --env staging
    OPENPANEL_API_KEY=... python openpanel_query.py funnel \\
        --preset core-funnel --env production --format markdown

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
import urllib.parse
import urllib.request
from typing import Mapping, Sequence

DEFAULT_API_URL = "https://openpanel.zitian.party/api"
API_KEY_ENV = "OPENPANEL_API_KEY"
API_URL_ENV = "OPENPANEL_API_URL"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

FUNNEL_PRESETS: dict[str, tuple[str, ...]] = {
    "core-funnel": (
        "upload_started",
        "upload_succeeded",
        "review_approved",
        "report_generated",
    ),
    "activation": (
        "upload_started",
        "upload_succeeded",
        "report_generated",
    ),
}


def _is_loopback(host: str) -> bool:
    return host.strip("[]").lower() in _LOOPBACK_HOSTS


def resolve_api_url(explicit: str | None) -> str:
    """Resolve and validate the API base URL: CLI flag > env var > default.

    The API key is sent as a header, so a plaintext ``http://`` endpoint would
    leak the secret on the wire. Reject any non-``https`` URL except loopback
    (localhost / 127.0.0.1 / ::1), which is safe for local development.
    """
    candidate = (explicit or os.environ.get(API_URL_ENV) or "").strip()
    url = candidate or DEFAULT_API_URL
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and parsed.hostname and _is_loopback(parsed.hostname):
        return url
    raise SystemExit(
        f"error: refusing to send the API key to a non-HTTPS endpoint: {url!r}; "
        "use https:// (or http:// only for localhost)."
    )


def resolve_api_key(env: dict[str, str] | None = None) -> str:
    """Return the API key from the environment or exit with a clear error."""
    source = env if env is not None else dict(os.environ)
    key = (source.get(API_KEY_ENV) or "").strip()
    if not key:
        raise SystemExit(
            f"error: {API_KEY_ENV} is not set; export it before querying OpenPanel."
        )
    return key


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
        payload["steps"] = resolve_funnel_steps(args)
    return payload


def format_markdown_summary(
    result: Mapping[str, object], *, command: str, env: str | None = None
) -> str:
    """Format an OpenPanel events or funnel response as a Markdown summary table."""
    scope = f" ({env})" if env else ""
    if command == "funnel":
        rows = result.get("steps") or result.get("data") or []
        lines = [
            f"### OpenPanel Funnel Summary{scope}",
            "",
            "| Step | Event | Count | Conversion |",
            "|---|---|---|---|",
        ]
        if isinstance(rows, list) and rows:
            first_count = 0
            for idx, item in enumerate(rows, start=1):
                if not isinstance(item, Mapping):
                    continue
                name = str(item.get("event") or item.get("name") or f"step_{idx}")
                count = int(item.get("count") or item.get("value") or 0)
                if idx == 1:
                    first_count = count
                pct = (
                    round((count / first_count) * 100.0, 1)
                    if first_count > 0
                    else (100.0 if count > 0 else 0.0)
                )
                lines.append(f"| {idx} | `{name}` | {count} | {pct}% |")
        else:
            lines.append("| - | (no funnel steps returned) | 0 | 0.0% |")
        return "\n".join(lines)

    events = result.get("events") or result.get("data") or []
    lines = [
        f"### OpenPanel Events Summary{scope}",
        "",
        f"Total returned: {len(events) if isinstance(events, list) else 0}",
    ]
    return "\n".join(lines)


def post_json(
    url: str, api_key: str, payload: dict[str, object]
) -> dict[str, object]:  # pragma: no cover - real network egress, injected in tests
    """POST a JSON payload and return the decoded response.

    Isolated so tests can monkeypatch it without making a network call.
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - scheme validated by resolve_api_url (https, or http only for loopback)
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


def run(args: argparse.Namespace, *, transport=None) -> dict[str, object]:
    """Resolve config, build the payload, and execute the request.

    ``transport`` is injectable for tests; when omitted it is resolved to the
    module-level :func:`post_json` at call time (so monkeypatching works).
    """
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
