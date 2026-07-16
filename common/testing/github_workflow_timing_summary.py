#!/usr/bin/env python3
"""Append a compact GitHub Actions workflow timing summary.

The script reads a workflow run through `gh run view` and writes queue time,
execution time, and per-job durations to a Markdown summary file.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.runtime.github_api import parse_github_time


@dataclass(frozen=True)
class JobTiming:
    name: str
    status: str
    conclusion: str
    started_at: datetime | None
    completed_at: datetime | None

    @property
    def duration_seconds(self) -> int | None:
        if self.started_at is None or self.completed_at is None:
            return None
        return max(0, int((self.completed_at - self.started_at).total_seconds()))


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "n/a"
    minutes, remainder = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {remainder}s"
    return f"{remainder}s"


def _job_from_payload(raw: dict[str, Any]) -> JobTiming:
    return JobTiming(
        name=str(raw.get("name") or "unknown"),
        status=str(raw.get("status") or "unknown"),
        conclusion=str(raw.get("conclusion") or "pending"),
        started_at=parse_github_time(raw.get("startedAt")),
        completed_at=parse_github_time(raw.get("completedAt")),
    )


def format_timing_summary(run: dict[str, Any], *, title: str) -> str:
    created_at = parse_github_time(run.get("createdAt"))
    updated_at = parse_github_time(run.get("updatedAt"))
    jobs = [_job_from_payload(job) for job in run.get("jobs", [])]

    started_jobs = [job for job in jobs if job.started_at is not None]
    completed_jobs = [job for job in jobs if job.completed_at is not None]
    first_started = min(
        (job.started_at for job in started_jobs if job.started_at), default=None
    )
    last_completed = max(
        (job.completed_at for job in completed_jobs if job.completed_at),
        default=updated_at,
    )

    queue_seconds = None
    if created_at and first_started:
        queue_seconds = max(0, int((first_started - created_at).total_seconds()))

    run_seconds = None
    if created_at and last_completed:
        run_seconds = max(0, int((last_completed - created_at).total_seconds()))

    execution_seconds = None
    if first_started and last_completed:
        execution_seconds = max(
            0, int((last_completed - first_started).total_seconds())
        )

    sorted_jobs = sorted(
        jobs,
        key=lambda job: (
            job.started_at or datetime.max.replace(tzinfo=timezone.utc),
            job.name,
        ),
    )

    longest = max(
        (job for job in completed_jobs if job.duration_seconds is not None),
        key=lambda j: j.duration_seconds or 0,
        default=None,
    )

    lines = [
        f"## {title}",
        "",
        f"- Run: `{run.get('url', 'unknown')}`",
        f"- Queue delay: `{format_duration(queue_seconds)}`",
        f"- Execution window: `{format_duration(execution_seconds)}`",
        f"- Run wall time: `{format_duration(run_seconds)}`",
    ]
    if longest is not None:
        lines.append(
            f"- Longest completed job: `{longest.name}` at `{format_duration(longest.duration_seconds)}`"
        )

    lines.extend(
        [
            "",
            "| Job | Result | Duration | Started | Completed |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for job in sorted_jobs:
        started = (
            job.started_at.isoformat().replace("+00:00", "Z")
            if job.started_at
            else "n/a"
        )
        completed = (
            job.completed_at.isoformat().replace("+00:00", "Z")
            if job.completed_at
            else "n/a"
        )
        result = job.conclusion if job.conclusion != "pending" else job.status
        lines.append(
            f"| `{job.name}` | `{result}` | `{format_duration(job.duration_seconds)}` | `{started}` | `{completed}` |"
        )

    return "\n".join(lines) + "\n"


def load_run(repo: str, run_id: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "gh",
            "run",
            "view",
            run_id,
            "--repo",
            repo,
            "--json",
            "createdAt,updatedAt,jobs,url,status,conclusion",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write GitHub Actions timing summary")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--title", default="Workflow Timing Summary")
    parser.add_argument("--summary-path", type=Path, required=True)
    args = parser.parse_args(argv)

    run = load_run(args.repo, args.run_id)
    summary = format_timing_summary(run, title=args.title)
    with args.summary_path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write(summary)
    print(f"Wrote workflow timing summary to {args.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
