#!/usr/bin/env python3
"""Wait for a GitHub commit status context to succeed."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubCommitStatus:
    context: str
    state: str
    description: str | None
    target_url: str | None


def _run_gh_status(repo: str, sha: str) -> list[GitHubCommitStatus]:
    args = ["gh", "api", f"repos/{repo}/commits/{sha}/status"]
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"failed to query GitHub commit statuses: {detail}")

    payload = json.loads(result.stdout or "{}")
    statuses = payload.get("statuses", [])
    if not isinstance(statuses, list):
        raise RuntimeError("GitHub commit status response did not contain a status list")

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


def _latest_status_for_context(
    statuses: list[GitHubCommitStatus],
    context: str,
) -> GitHubCommitStatus | None:
    for status in statuses:
        if status.context == context:
            return status
    return None


def wait_for_status_success(
    *,
    repo: str,
    sha: str,
    context: str,
    timeout_seconds: int = 300,
    poll_seconds: int = 10,
    failure_confirmation_seconds: int = 0,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> GitHubCommitStatus:
    """Poll GitHub until the requested commit status succeeds or fails."""
    deadline = monotonic() + timeout_seconds
    terminal_failure_seen = False

    while True:
        status = _latest_status_for_context(_run_gh_status(repo, sha), context)
        if status is None:
            terminal_failure_seen = False
            print(f"Waiting for GitHub status {context!r} on {sha}: not found")
        else:
            print(
                f"GitHub status {context!r} on {sha}: "
                f"state={status.state} description={status.description!r} "
                f"url={status.target_url}"
            )
            if status.state == "success":
                return status
            if status.state in {"failure", "error"}:
                if failure_confirmation_seconds > 0 and not terminal_failure_seen:
                    print(
                        f"Confirming terminal GitHub status {context!r} on {sha} "
                        f"after {failure_confirmation_seconds}s"
                    )
                    terminal_failure_seen = True
                    sleep(failure_confirmation_seconds)
                    continue
                raise RuntimeError(
                    f"{context} failed for {sha}: "
                    f"{status.description or status.state} {status.target_url or ''}"
                )
            terminal_failure_seen = False

        if monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for GitHub status {context!r} on {sha}"
            )
        sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wait for a GitHub commit status context to succeed."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument(
        "--failure-confirmation-seconds",
        type=int,
        default=0,
        help="Re-poll after a failure/error status before failing.",
    )
    args = parser.parse_args()

    try:
        wait_for_status_success(
            repo=args.repo,
            sha=args.sha,
            context=args.context,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            failure_confirmation_seconds=args.failure_confirmation_seconds,
        )
    except (RuntimeError, TimeoutError) as exc:
        print(f"::error title=GitHub status wait failed::{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
