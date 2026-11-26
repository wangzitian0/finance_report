#!/usr/bin/env python3
"""Thin OpenPanel query CLI for inspecting frontend product-analytics data.

Uses Python stdlib only for OpenPanel export API URL validation, API key
resolution, declarative funnel preset loading, payload construction, Markdown
summary rendering, and HTTP transport.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_API_URL = "https://openpanel.zitian.party/api"
API_URL_ENV = "OPENPANEL_API_URL"
_OPENPANEL_KEY_ENV = "_".join(("OPENPANEL", "API", "KEY"))
_OPENPANEL_URL_ENV = "_".join(("OPENPANEL", "API", "URL"))
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
OPENPANEL_CONTRACT_PATH = (
    Path(__file__).resolve().parent / "data" / "openpanel_analytics.json"
)


def _is_loopback_host(host: str) -> bool:
    return host.strip("[]").lower() in _LOOPBACK_HOSTS


def resolve_openpanel_api_url(
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    default_url: str = DEFAULT_API_URL,
) -> str:
    src = os.environ if env is None else env
    url = (explicit or src.get(_OPENPANEL_URL_ENV) or "").strip() or default_url
    parsed = urlparse(url)
    if parsed.scheme == "https" or (
        parsed.scheme == "http"
        and parsed.hostname
        and _is_loopback_host(parsed.hostname)
    ):
        return url
    raise SystemExit(
        f"error: refusing to send the API key to a non-HTTPS endpoint: {url!r}; "
        "use https:// (or http:// only for localhost)."
    )


def resolve_openpanel_api_key(env: Mapping[str, str] | None = None) -> str:
    key = ((os.environ if env is None else env).get(_OPENPANEL_KEY_ENV) or "").strip()
    if not key:
        raise SystemExit(
            f"error: {_OPENPANEL_KEY_ENV} is not set; export it before querying OpenPanel."
        )
    return key


def load_openpanel_funnel_presets(
    contract_path: str | Path,
) -> dict[str, tuple[str, ...]]:
    raw = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    funnels = raw.get("funnels") if isinstance(raw, Mapping) else None
    if not isinstance(funnels, list):
        raise ValueError(f"{contract_path}: missing 'funnels' list")
    presets: dict[str, tuple[str, ...]] = {}
    for entry in (i for i in funnels if isinstance(i, Mapping)):
        steps_raw = entry.get("steps")
        if not isinstance(steps_raw, list):
            continue
        steps = tuple(s for step in steps_raw if (s := str(step).strip()))
        if len(steps) < 2:
            continue
        preset = str(entry.get("preset") or "").strip()
        if not preset:
            nm = str(entry.get("name") or "").lower()
            ds = str(entry.get("description") or "").lower()
            if "north star" in nm or "core loop" in ds or "review" in nm:
                preset = "core-funnel"
            elif "activation" in ds or "upload" in nm:
                preset = "activation"
        if preset:
            presets[preset] = steps
    return presets


def build_openpanel_payload(
    *,
    command: str,
    limit: int = 100,
    env: str | None = None,
    event: str | None = None,
    steps: Sequence[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"limit": limit}
    if env:
        payload["filters"] = [{"name": "environment", "operator": "is", "value": [env]}]
    if command == "events":
        payload["event"] = event or "*"
    elif command == "funnel":
        payload["steps"] = list(steps or ())
    return payload


def format_openpanel_markdown(
    result: Mapping[str, object], *, command: str, env: str | None = None
) -> str:
    scope = f" ({env})" if env else ""
    if command != "funnel":
        events = result.get("events") or result.get("data") or []
        total = len(events) if isinstance(events, list) else 0
        return f"### OpenPanel Events Summary{scope}\n\nTotal returned: {total}"
    rows = result.get("steps") or result.get("data") or []
    lines = [
        f"### OpenPanel Funnel Summary{scope}",
        "",
        "| Step | Event | Count | Conversion |",
        "|---|---|---|---|",
    ]
    if isinstance(rows, list) and rows:
        first = 0
        for idx, item in enumerate(rows, start=1):
            if not isinstance(item, Mapping):
                continue
            nm = str(item.get("event") or item.get("name") or f"step_{idx}")
            cnt = int(item.get("count") or item.get("value") or 0)
            if idx == 1:
                first = cnt
            pct = (
                round((cnt / first) * 100.0, 1)
                if first > 0
                else (100.0 if cnt > 0 else 0.0)
            )
            lines.append(f"| {idx} | `{nm}` | {cnt} | {pct}% |")
    else:
        lines.append("| - | (no funnel steps returned) | 0 | 0.0% |")
    return "\n".join(lines)


def post_openpanel_json(
    url: str,
    api_key: str,
    payload: Mapping[str, object],
    *,
    timeout: float = 30.0,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> dict[str, object]:
    hdrs = {"Content-Type": "application/json", "openpanel-client-secret": api_key}
    data = json.dumps(dict(payload)).encode()
    req = urllib.request.Request(url, headers=hdrs, data=data, method="POST")  # noqa: S310
    with opener(req, timeout=timeout) as resp:  # type: ignore[attr-defined]
        raw = resp.read()
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
    body = json.loads(text) if text.strip() else None
    if not isinstance(body, dict):
        raise ValueError(f"OpenPanel response from {url} is not a JSON object")
    return body


FUNNEL_PRESETS: dict[str, tuple[str, ...]] = load_openpanel_funnel_presets(
    OPENPANEL_CONTRACT_PATH
)


def resolve_api_url(explicit: str | None) -> str:
    """Resolve and validate the API base URL."""
    return resolve_openpanel_api_url(explicit, default_url=DEFAULT_API_URL)


def resolve_api_key(env: Mapping[str, str] | None = None) -> str:
    """Return the API key from the environment."""
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
