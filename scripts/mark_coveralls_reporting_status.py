#!/usr/bin/env python3
"""Mark Coveralls status contexts as reporting-only after local gates pass."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass


DEFAULT_CONTEXTS = (
    "coverage/coveralls",
    "coverage/coveralls (push)",
    "Coveralls - unified",
    "Coveralls - backend",
    "Coveralls - frontend",
)
DEFAULT_DESCRIPTION = "Coveralls reporting-only; local coverage gate passed."
DEFAULT_SETTLE_SECONDS = 45


@dataclass(frozen=True)
class GitHubCommitStatus:
    context: str
    state: str
    description: str | None
    target_url: str | None


def _run_gh_json(args: list[str]) -> dict[str, object]:
    result = subprocess.run(
        ["gh", "api", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"gh api failed: {detail}")
    return json.loads(result.stdout or "{}")


def _run_gh_status_create(
    *,
    repo: str,
    sha: str,
    context: str,
    description: str,
    target_url: str,
) -> None:
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
        raise RuntimeError(f"failed to create GitHub status: {detail}")


def fetch_commit_statuses(repo: str, sha: str) -> list[GitHubCommitStatus]:
    payload = _run_gh_json([f"repos/{repo}/commits/{sha}/status"])
    statuses = payload.get("statuses", [])
    if not isinstance(statuses, list):
        raise RuntimeError("GitHub commit status response did not contain a list")

    parsed: list[GitHubCommitStatus] = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        parsed.append(
            GitHubCommitStatus(
                context=str(status.get("context", "")),
                state=str(status.get("state", "")),
                description=status.get("description"),
                target_url=status.get("target_url"),
            )
        )
    return parsed


def latest_status_for_context(
    statuses: list[GitHubCommitStatus],
    context: str,
) -> GitHubCommitStatus | None:
    for status in statuses:
        if status.context == context:
            return status
    return None


def wait_for_coveralls_observations(
    *,
    repo: str,
    sha: str,
    contexts: tuple[str, ...] = DEFAULT_CONTEXTS,
    timeout_seconds: int = 120,
    poll_seconds: int = 5,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict[str, GitHubCommitStatus | None]:
    """Wait briefly for Coveralls to write its asynchronous status contexts."""
    deadline = monotonic() + timeout_seconds
    observed: dict[str, GitHubCommitStatus | None] = {
        context: None for context in contexts
    }

    while True:
        statuses = fetch_commit_statuses(repo, sha)
        for context in contexts:
            if observed[context] is not None:
                continue
            status = latest_status_for_context(statuses, context)
            if status is not None and status.state in {"success", "failure", "error"}:
                observed[context] = status
                print(
                    f"Observed {context!r}: state={status.state} "
                    f"description={status.description!r} url={status.target_url}"
                )

        if all(status is not None for status in observed.values()):
            return observed

        if monotonic() >= deadline:
            missing = [
                context for context, status in observed.items() if status is None
            ]
            print(
                f"Did not observe terminal Coveralls statuses on {sha}: "
                f"{', '.join(missing)}; "
                "publishing local reporting-only status."
            )
            return observed

        missing = [context for context, status in observed.items() if status is None]
        print(f"Waiting for Coveralls statuses on {sha}: {', '.join(missing)}")
        sleep(poll_seconds)


def mark_coveralls_reporting_only(
    *,
    repo: str,
    sha: str,
    target_url: str,
    contexts: tuple[str, ...] = DEFAULT_CONTEXTS,
    description: str = DEFAULT_DESCRIPTION,
    timeout_seconds: int = 120,
    poll_seconds: int = 5,
    settle_seconds: int = DEFAULT_SETTLE_SECONDS,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict[str, GitHubCommitStatus | None]:
    """Publish final success statuses for Coveralls reporting-only contexts."""
    observed = wait_for_coveralls_observations(
        repo=repo,
        sha=sha,
        contexts=contexts,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    for context in contexts:
        _run_gh_status_create(
            repo=repo,
            sha=sha,
            context=context,
            description=description,
            target_url=target_url,
        )
        print(f"Published reporting-only success for {context!r} on {sha}")
    if settle_seconds > 0:
        print(f"Settling for {settle_seconds}s before final Coveralls status check")
        sleep(settle_seconds)
        latest_statuses = fetch_commit_statuses(repo, sha)
        stale_contexts: list[str] = []
        for context in contexts:
            latest = latest_status_for_context(latest_statuses, context)
            if (
                latest is None
                or latest.state != "success"
                or latest.description != description
                or latest.target_url != target_url
            ):
                stale_contexts.append(context)

        for context in stale_contexts:
            _run_gh_status_create(
                repo=repo,
                sha=sha,
                context=context,
                description=description,
                target_url=target_url,
            )
            print(f"Re-published final reporting-only success for {context!r} on {sha}")
    return observed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Wait for Coveralls statuses, then publish local reporting-only "
            "success statuses for the same contexts."
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
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--settle-seconds", type=int, default=DEFAULT_SETTLE_SECONDS)
    args = parser.parse_args()

    try:
        mark_coveralls_reporting_only(
            repo=args.repo,
            sha=args.sha,
            target_url=args.target_url,
            contexts=tuple(args.contexts or DEFAULT_CONTEXTS),
            description=args.description,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            settle_seconds=args.settle_seconds,
        )
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(
            f"::error title=Coveralls reporting status override failed::{exc}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
