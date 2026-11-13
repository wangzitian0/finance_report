#!/usr/bin/env python3
"""Append a compact GitHub Actions workflow timing summary.

The script reads a workflow run through `gh run view` and writes queue time,
execution time, and per-job durations to a Markdown summary file.

With `--budget` it also compares the execution window with the owner's pipeline
budget (#2688). The exit code is 1 only when the run cannot be measured; an
overrun never fails the caller. `--comment` posts the overrun once per run on the
PR (`--pr`) or, without `--pr`, on the open `ci-budget` issue (opened when none
exists). The time before
the first job starts never counts: it depends on runner capacity, not on the
workflow. A job that waits for a runner later in the run does count.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.runtime.github_api import parse_github_time

# The one machine copy of the budgets (#2688, #2996), in seconds. Source: the zitian
# Workspace tier, section "Pipeline time contract". Docs link that tier and repeat no
# number. Each value is the upper bound. The release window starts at the first job of the dispatched deploy run, so the
# tag-push image run and the gap before the dispatch are not in it.
PIPELINE_BUDGET_SECONDS: dict[str, int] = {
    "pr": 4 * 60,
    "main": 8 * 60,
    "release": 15 * 60,
}
SLOWEST_JOBS_IN_COMMENT = 3
BUDGET_ISSUE_LABEL = "ci-budget"


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


@dataclass(frozen=True)
class RunTiming:
    jobs: list[JobTiming]
    queue_seconds: int | None
    execution_seconds: int | None
    run_seconds: int | None


@dataclass(frozen=True)
class BudgetVerdict:
    kind: str
    budget_seconds: int
    execution_seconds: int | None

    @property
    def measured(self) -> bool:
        return self.execution_seconds is not None

    @property
    def exceeded(self) -> bool:
        return (
            self.execution_seconds is not None
            and self.execution_seconds > self.budget_seconds
        )

    def describe(self) -> str:
        measured = format_duration(self.execution_seconds)
        budget = format_duration(self.budget_seconds)
        if self.execution_seconds is None:
            state = "not measured"
        elif self.exceeded:
            state = "OVER"
        else:
            state = "within"
        return f"Budget `{self.kind}`: execution window `{measured}` of `{budget}` ({state})"


def run_timing(run: dict[str, Any]) -> RunTiming:
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
    return RunTiming(jobs, queue_seconds, execution_seconds, run_seconds)


def budget_verdict(run: dict[str, Any], kind: str) -> BudgetVerdict:
    return BudgetVerdict(
        kind=kind,
        budget_seconds=PIPELINE_BUDGET_SECONDS[kind],
        execution_seconds=run_timing(run).execution_seconds,
    )


def format_timing_summary(
    run: dict[str, Any], *, title: str, budget_kind: str | None = None
) -> str:
    timing = run_timing(run)
    jobs = timing.jobs
    queue_seconds = timing.queue_seconds
    execution_seconds = timing.execution_seconds
    run_seconds = timing.run_seconds
    completed_jobs = [job for job in jobs if job.completed_at is not None]

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
    if budget_kind is not None:
        lines.append(f"- {budget_verdict(run, budget_kind).describe()}")

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


def format_overrun_comment(
    run: dict[str, Any], verdict: BudgetVerdict, *, title: str
) -> str:
    slowest = sorted(
        (job for job in run_timing(run).jobs if job.duration_seconds is not None),
        key=lambda job: job.duration_seconds or 0,
        reverse=True,
    )[:SLOWEST_JOBS_IN_COMMENT]
    lines = [
        f"Pipeline budget exceeded: **{title}** ran for "
        f"`{format_duration(verdict.execution_seconds)}` against the "
        f"`{format_duration(verdict.budget_seconds)}` `{verdict.kind}` budget.",
        "",
        f"Run: {run.get('url', 'unknown')}",
        "",
        "Slowest jobs:",
    ]
    lines.extend(
        f"- `{job.name}`: `{format_duration(job.duration_seconds)}`" for job in slowest
    )
    return "\n".join(lines) + "\n"


def _gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], check=True, text=True, capture_output=True
    ).stdout


def post_overrun(repo: str, pr: str | None, run: dict[str, Any], body: str) -> str:
    """Comment on the PR, or on the open `ci-budget` issue; open one when none exists.

    Return the number of the target, or "" when the run is already named there.
    """
    target = pr or _gh(
        "issue", "list", "--repo", repo, "--label", BUDGET_ISSUE_LABEL,
        "--state", "open", "--json", "number", "--jq", ".[0].number // empty",
    ).strip()
    if not target:
        _gh("label", "create", BUDGET_ISSUE_LABEL, "--repo", repo, "--force")
        _gh(
            "issue", "create", "--repo", repo, "--label", BUDGET_ISSUE_LABEL,
            "--title", "CI pipeline budget exceeded on main", "--body", body,
        )
        return "new"
    if already_commented(repo, target, str(run.get("url", "unknown"))):
        return ""
    _gh("issue", "comment", target, "--repo", repo, "--body", body)
    return target


def already_commented(repo: str, issue: str, run_url: str) -> bool:
    """True when a comment on the issue already names this run (a rerun posts once)."""
    try:
        listing = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                issue,
                "--repo",
                repo,
                "--json",
                "comments",
                "--jq",
                ".comments[].body",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    # The URL must end the number: runs/9 must not match a comment for runs/90.
    return run_url != "unknown" and bool(
        re.search(re.escape(run_url) + r"(?!\d)", listing.stdout)
    )


def check_budget(
    run: dict[str, Any],
    *,
    kind: str,
    title: str,
    repo: str,
    pr: str | None,
    comment: bool,
) -> int:
    """Print the verdict. Return 1 only when the run cannot be measured."""
    verdict = budget_verdict(run, kind)
    print(verdict.describe())
    if not verdict.measured:
        print(f"::error::The `{kind}` budget cannot be checked: no job has run.")
        return 1
    if not verdict.exceeded:
        return 0
    print(
        f"::warning::Pipeline budget exceeded: {title} ran "
        f"{format_duration(verdict.execution_seconds)} against "
        f"{format_duration(verdict.budget_seconds)} ({kind})."
    )
    if comment:
        try:
            target = post_overrun(
                repo, pr, run, format_overrun_comment(run, verdict, title=title)
            )
            print(f"Overrun reported on {target or 'an earlier comment for this run'}.")
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"::warning::Could not report the overrun: {exc}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write GitHub Actions timing summary")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--title", default="Workflow Timing Summary")
    parser.add_argument("--summary-path", type=Path, required=True)
    parser.add_argument(
        "--budget",
        choices=sorted(PIPELINE_BUDGET_SECONDS),
        help="Compare the execution window with this budget and print the verdict.",
    )
    parser.add_argument(
        "--comment",
        action="store_true",
        help="Report an overrun of the --budget on the PR or the ci-budget issue.",
    )
    parser.add_argument("--pr", help="PR number that receives the overrun comment.")
    args = parser.parse_args(argv)
    if args.comment and not args.budget:
        parser.error("--comment needs --budget")

    run = load_run(args.repo, args.run_id)
    summary = format_timing_summary(run, title=args.title, budget_kind=args.budget)
    with args.summary_path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write(summary)
    print(f"Wrote workflow timing summary to {args.summary_path}")
    if args.budget is None:
        return 0
    return check_budget(
        run,
        kind=args.budget,
        title=args.title,
        repo=args.repo,
        pr=args.pr,
        comment=args.comment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
