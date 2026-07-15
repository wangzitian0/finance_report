#!/usr/bin/env python3
"""Wait until an automatic staging workflow run reaches its FIFO train turn."""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from common.runtime.github_api import GitHubActionsClient, parse_github_time

ACTIVE_STATUSES = frozenset(
    {"queued", "in_progress", "requested", "waiting", "pending"}
)


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int
    status: str
    conclusion: str | None
    created_at: datetime
    url: str
    display_title: str


def workflow_run_from_payload(payload: dict[str, Any]) -> WorkflowRun:
    created_at = parse_github_time(payload.get("created_at"))
    if created_at is None:
        raise ValueError("workflow run is missing created_at")
    return WorkflowRun(
        run_id=int(payload["id"]),
        status=str(payload.get("status") or ""),
        conclusion=payload.get("conclusion"),
        created_at=created_at,
        url=str(payload.get("html_url") or payload.get("url") or ""),
        display_title=str(
            payload.get("display_title") or payload.get("name") or payload["id"]
        ),
    )


def older_active_runs(
    current: WorkflowRun, runs: list[WorkflowRun]
) -> list[WorkflowRun]:
    return sorted(
        [
            run
            for run in runs
            if run.run_id != current.run_id
            and run.created_at < current.created_at
            and run.status in ACTIVE_STATUSES
        ],
        key=lambda run: (run.created_at, run.run_id),
    )


def wait_for_train_turn(
    *,
    client: GitHubActionsClient,
    run_id: int,
    timeout_seconds: int,
    poll_seconds: int,
    output: Any = sys.stdout,
) -> None:
    current_payload = client.get_run_payload(run_id)
    current = workflow_run_from_payload(current_payload)
    workflow_id = int(current_payload["workflow_id"])
    deadline = time.monotonic() + timeout_seconds

    print(
        f"Post-merge train gate: run {current.run_id} waits for older active runs "
        f"in workflow {workflow_id}.",
        file=output,
        flush=True,
    )

    while True:
        run_payloads = client.list_workflow_runs(workflow_id)
        runs = [workflow_run_from_payload(payload) for payload in run_payloads]
        blockers = older_active_runs(current, runs)

        if not blockers:
            print(
                "Post-merge train gate: this run is at the front of the train.",
                file=output,
                flush=True,
            )
            return

        blocker_summary = ", ".join(
            f"{run.run_id}:{run.status}" for run in blockers[:5]
        )
        print(
            f"Post-merge train gate: waiting for {len(blockers)} older run(s): {blocker_summary}",
            file=output,
            flush=True,
        )

        if time.monotonic() + poll_seconds > deadline:
            urls = "\n".join(
                f"- {run.run_id} {run.status} {run.url}" for run in blockers
            )
            raise TimeoutError(
                "Timed out waiting for older post-merge staging workflow runs to finish:\n"
                f"{urls}"
            )

        time.sleep(poll_seconds)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--run-id", type=int, default=int(os.environ.get("GITHUB_RUN_ID", "0") or "0")
    )
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    parser.add_argument("--timeout-seconds", type=int, default=21_600)
    parser.add_argument("--poll-seconds", type=int, default=30)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    missing = [
        name
        for name, value in {
            "repository": args.repository,
            "run-id": args.run_id,
            "token": args.token,
        }.items()
        if not value
    ]
    if missing:
        print(f"Missing required GitHub context: {', '.join(missing)}", file=sys.stderr)
        return 2

    client = GitHubActionsClient(
        repository=args.repository,
        token=args.token,
        api_url=args.api_url,
        user_agent="finance-report-post-merge-train/1.0",
    )
    try:
        wait_for_train_turn(
            client=client,
            run_id=args.run_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (RuntimeError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
