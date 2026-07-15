#!/usr/bin/env python3
"""Wait until the cheap CI jobs (lint and ac-traceability) succeed for a given commit SHA."""

from __future__ import annotations

import argparse
import sys
import time
from common.runtime import github_api

# Keep the established monkeypatch seam pointed at the shared transport.
GitHubActionsClient = github_api.GitHubActionsClient
urllib = github_api.urllib


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
