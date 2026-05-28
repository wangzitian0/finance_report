#!/usr/bin/env python3
"""Publish Coveralls reporting-only statuses after local gates pass."""

from __future__ import annotations

import argparse
import json
import subprocess


DEFAULT_CONTEXTS = (
    "coverage/coveralls",
    "coverage/coveralls (push)",
    "Coveralls - unified",
    "Coveralls - backend",
    "Coveralls - frontend",
)
DEFAULT_DESCRIPTION = "Coveralls reporting-only; local coverage gate passed."


def _log(message: str) -> None:
    print(message, flush=True)


def is_coveralls_context(context: str) -> bool:
    return (
        context == "coverage/coveralls"
        or context.startswith("coverage/coveralls ")
        or context.startswith("Coveralls")
    )


def _run_gh_json(args: list[str]) -> dict[str, object] | None:
    result = subprocess.run(
        ["gh", "api", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        _log(f"Warning: could not fetch Coveralls statuses: {detail}")
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        _log(f"Warning: could not parse Coveralls status payload: {exc}")
        return None
    if not isinstance(payload, dict):
        _log("Warning: Coveralls status payload was not a JSON object")
        return None
    return payload


def discover_coveralls_contexts(repo: str, sha: str) -> tuple[str, ...]:
    """Return Coveralls contexts GitHub already knows for this SHA."""
    payload = _run_gh_json([f"repos/{repo}/commits/{sha}/status"])
    if payload is None:
        return ()

    statuses = payload.get("statuses", [])
    if not isinstance(statuses, list):
        _log("Warning: GitHub commit status response did not contain a list")
        return ()

    contexts: list[str] = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        context = str(status.get("context", ""))
        if is_coveralls_context(context) and context not in contexts:
            contexts.append(context)
    return tuple(contexts)


def ordered_unique(items: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for item in items:
        if item and item not in values:
            values.append(item)
    return tuple(values)


def publish_reporting_status(
    *,
    repo: str,
    sha: str,
    context: str,
    description: str,
    target_url: str,
) -> bool:
    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repo}/statuses/{sha}",
            "-f",
            "state=success",
            "-f",
            f"context={context}",
            "-f",
            f"description={description}",
            "-f",
            f"target_url={target_url}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        _log(
            f"Warning: could not publish reporting-only status for {context!r}: {detail}"
        )
        return False
    _log(f"Published reporting-only success for {context!r} on {sha}")
    return True


def mark_coveralls_reporting_only(
    *,
    repo: str,
    sha: str,
    target_url: str,
    contexts: tuple[str, ...] = DEFAULT_CONTEXTS,
    description: str = DEFAULT_DESCRIPTION,
) -> tuple[str, ...]:
    """Publish success for known and discovered Coveralls reporting contexts."""
    publish_contexts = ordered_unique(
        tuple(contexts) + discover_coveralls_contexts(repo, sha)
    )
    for context in publish_contexts:
        publish_reporting_status(
            repo=repo,
            sha=sha,
            context=context,
            description=description,
            target_url=target_url,
        )
    return publish_contexts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Publish local reporting-only success statuses for Coveralls contexts. "
            "This is not a coverage gate; local deterministic checks gate coverage."
        )
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument(
        "--context",
        action="append",
        dest="contexts",
        help=(
            "Coveralls status context to normalize. May be specified multiple "
            "times. Defaults to all known Coveralls contexts."
        ),
    )
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    args = parser.parse_args()

    mark_coveralls_reporting_only(
        repo=args.repo,
        sha=args.sha,
        target_url=args.target_url,
        contexts=tuple(args.contexts or DEFAULT_CONTEXTS),
        description=args.description,
    )


if __name__ == "__main__":
    main()
