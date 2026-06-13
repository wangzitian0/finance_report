#!/usr/bin/env python3
"""Wait until an automatic staging workflow run reaches its FIFO train turn."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


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


def parse_github_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def workflow_run_from_payload(payload: dict[str, Any]) -> WorkflowRun:
    return WorkflowRun(
        run_id=int(payload["id"]),
        status=str(payload.get("status") or ""),
        conclusion=payload.get("conclusion"),
        created_at=parse_github_time(str(payload["created_at"])),
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


class GitHubActionsClient:
    def __init__(
        self, *, repository: str, token: str, api_url: str = "https://api.github.com"
    ) -> None:
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")

    def _request_json(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        url = f"{self.api_url}/repos/{self.repository}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "finance-report-post-merge-train/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API HTTP {exc.code} for {url}: {body[:500]}"
            ) from exc

    def get_run_payload(self, run_id: int) -> dict[str, Any]:
        return self._request_json(f"/actions/runs/{run_id}")

    def list_workflow_runs(
        self, workflow_id: int, *, max_pages: int = 5
    ) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            payload = self._request_json(
                f"/actions/workflows/{workflow_id}/runs",
                {"per_page": "100", "page": str(page)},
            )
            batch = payload.get("workflow_runs", [])
            if not isinstance(batch, list) or not batch:
                break
            runs.extend(batch)
            if len(batch) < 100:
                break
        return runs


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
        repository=args.repository, token=args.token, api_url=args.api_url
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
