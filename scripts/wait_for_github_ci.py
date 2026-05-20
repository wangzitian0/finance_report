#!/usr/bin/env python3
"""Wait for the matching GitHub Actions CI run to finish successfully."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GitHubRun:
    database_id: int | None
    status: str
    conclusion: str
    url: str


def _run_gh_list(
    *,
    repo: str,
    sha: str,
    workflow: str,
    branch: str,
    event: str,
) -> list[GitHubRun]:
    # Keep this command equivalent to: gh run list --workflow CI --commit <sha>.
    args = [
        "gh",
        "run",
        "list",
        "--repo",
        repo,
        "--workflow",
        workflow,
        "--branch",
        branch,
        "--commit",
        sha,
        "--event",
        event,
        "--json",
        "databaseId,status,conclusion,url",
        "--limit",
        "10",
    ]
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "failed to query GitHub Actions CI runs: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    payload = json.loads(result.stdout or "[]")
    runs: list[GitHubRun] = []
    for item in payload:
        runs.append(
            GitHubRun(
                database_id=item.get("databaseId"),
                status=str(item.get("status") or ""),
                conclusion=str(item.get("conclusion") or ""),
                url=str(item.get("url") or ""),
            )
        )
    return runs


def wait_for_matching_ci(
    *,
    repo: str,
    sha: str,
    workflow: str = "CI",
    branch: str = "main",
    event: str = "push",
    timeout_seconds: int = 2700,
    poll_seconds: int = 30,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> GitHubRun:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        runs = _run_gh_list(
            repo=repo,
            sha=sha,
            workflow=workflow,
            branch=branch,
            event=event,
        )
        if not runs:
            print(f"No {workflow} run found yet for {sha}; waiting...")
            sleep(poll_seconds)
            continue

        run = runs[0]
        print(
            f"{workflow} for {sha}: status={run.status} "
            f"conclusion={run.conclusion or 'pending'} url={run.url}"
        )
        if run.status == "completed":
            if run.conclusion == "success":
                return run
            raise RuntimeError(
                "matching CI run failed before staging validation: "
                f"conclusion={run.conclusion or 'unknown'} url={run.url}"
            )
        sleep(poll_seconds)

    raise TimeoutError(f"timed out waiting for matching {workflow} success for {sha}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for a matching GitHub Actions CI run to finish successfully."
    )
    parser.add_argument(
        "--repo", required=True, help="GitHub repository, e.g. owner/repo."
    )
    parser.add_argument("--sha", required=True, help="Full commit SHA to match.")
    parser.add_argument("--workflow", default="CI", help="Workflow name to wait for.")
    parser.add_argument("--branch", default="main", help="Branch name to match.")
    parser.add_argument(
        "--event", default="push", help="GitHub Actions event to match."
    )
    parser.add_argument("--timeout-seconds", type=int, default=2700)
    parser.add_argument("--poll-seconds", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        wait_for_matching_ci(
            repo=args.repo,
            sha=args.sha,
            workflow=args.workflow,
            branch=args.branch,
            event=args.event,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (RuntimeError, TimeoutError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
