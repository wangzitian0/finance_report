#!/usr/bin/env python3
"""Wait until the cheap CI jobs (lint and ac-traceability) succeed for a given commit SHA."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


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
                "User-Agent": "finance-report-wait-for-cheap-ci/1.0",
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

    def get_workflow_runs(self, commit_sha: str) -> list[dict[str, Any]]:
        # Get runs for ci.yml workflow for the given commit SHA
        path = "/actions/workflows/ci.yml/runs"
        payload = self._request_json(path, {"head_sha": commit_sha})
        return payload.get("workflow_runs") or []

    def get_run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        path = f"/actions/runs/{run_id}/jobs"
        payload = self._request_json(path)
        return payload.get("jobs") or []


def wait_for_cheap_ci(
    *,
    repository: str,
    token: str,
    commit_sha: str,
    poll_seconds: int = 15,
    timeout_seconds: int = 600,
) -> int:
    client = GitHubActionsClient(repository=repository, token=token)
    start_time = time.monotonic()

    print(
        f"Starting wait for cheap CI on repo={repository} commit={commit_sha} timeout={timeout_seconds}s"
    )

    while True:
        elapsed = int(time.monotonic() - start_time)
        if elapsed > timeout_seconds:
            print(
                f"::error::Timeout waiting for CI workflow run to be registered/finish for commit {commit_sha}"
            )
            return 1

        try:
            runs = client.get_workflow_runs(commit_sha)
        except Exception as exc:
            print(f"Warning: Failed to fetch workflow runs: {exc}. Retrying...")
            runs = []

        if not runs:
            print(
                f"CI workflow run not found yet. Elapsed {elapsed}s. Retrying in {poll_seconds}s..."
            )
            time.sleep(poll_seconds)
            continue

        # Prefer completed successful runs, then active/in-progress runs, then fallback to newest run overall.
        successful_runs = [r for r in runs if r.get("conclusion") == "success"]
        active_statuses = {"queued", "in_progress", "requested", "waiting", "pending"}
        active_runs = [r for r in runs if r.get("status") in active_statuses]

        if successful_runs:
            selected_run = sorted(
                successful_runs, key=lambda r: int(r["id"]), reverse=True
            )[0]
        elif active_runs:
            selected_run = sorted(
                active_runs, key=lambda r: int(r["id"]), reverse=True
            )[0]
        else:
            selected_run = sorted(runs, key=lambda r: int(r["id"]), reverse=True)[0]

        run_id = int(selected_run["id"])
        print(
            f"Selected CI workflow run ID: {run_id} (status: {selected_run.get('status')}, conclusion: {selected_run.get('conclusion')})"
        )

        try:
            jobs = client.get_run_jobs(run_id)
        except Exception as exc:
            print(f"Warning: Failed to fetch jobs for run {run_id}: {exc}. Retrying...")
            jobs = []

        if jobs:
            # We want to check status of:
            # 1. Lint (job name is "Lint")
            # 2. AC Traceability Check (job name is "AC Traceability Check")
            target_jobs = {"Lint": None, "AC Traceability Check": None}

            for job in jobs:
                name = job.get("name")
                if name in target_jobs:
                    target_jobs[name] = job

            # Check status of target jobs
            all_done = True
            all_success = True
            missing_jobs = []

            for name, job in target_jobs.items():
                if job is None:
                    # Job might not be created/scheduled yet by GitHub Actions
                    missing_jobs.append(name)
                    all_done = False
                    continue

                status = job.get("status")
                conclusion = job.get("conclusion")

                print(f"Job '{name}': status={status}, conclusion={conclusion}")

                if status != "completed":
                    all_done = False
                elif conclusion != "success":
                    all_success = False

            if missing_jobs:
                print(f"Waiting for jobs to be created: {missing_jobs}")

            if all_done:
                if all_success:
                    print(
                        "✅ Both cheap CI jobs (Lint and AC Traceability Check) succeeded!"
                    )
                    return 0
                else:
                    # If this run failed, but another run is active or successful, do not fail yet
                    if not active_runs and len(successful_runs) <= 0:
                        print("❌ One of the cheap CI jobs failed. Failing gate.")
                        return 1
                    else:
                        print(
                            "Selected run failed/completed, but other active or successful runs exist. Retrying..."
                        )

        print(
            f"Waiting for cheap CI jobs. Elapsed {elapsed}s. Retrying in {poll_seconds}s..."
        )
        time.sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wait for cheap CI jobs.")
    parser.add_argument(
        "--repository", required=True, help="GitHub repository (owner/repo)"
    )
    parser.add_argument("--token", required=True, help="GitHub token")
    parser.add_argument("--commit-sha", required=True, help="Commit SHA to check")
    parser.add_argument(
        "--poll-seconds", type=int, default=15, help="Poll interval in seconds"
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=600, help="Max wait timeout in seconds"
    )

    args = parser.parse_args(argv)
    return wait_for_cheap_ci(
        repository=args.repository,
        token=args.token,
        commit_sha=args.commit_sha,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
