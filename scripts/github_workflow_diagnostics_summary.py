#!/usr/bin/env python3
"""Append workflow diagnostics focused on CI blockers and stale staging."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


@dataclass(frozen=True)
class JobStep:
    name: str
    conclusion: str


@dataclass(frozen=True)
class JobState:
    job_id: int
    name: str
    conclusion: str
    steps: tuple[JobStep, ...]


@dataclass(frozen=True)
class HealthSnapshot:
    url: str
    http_status: int
    healthy: bool
    git_sha: str
    error: str | None = None


def _gh_json(args: list[str]) -> Any:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"GitHub CLI command failed: {' '.join(args)} :: {detail}")
    return json.loads(result.stdout or "{}")


def _load_run_jobs(repo: str, run_id: str) -> list[JobState]:
    payload = _gh_json(
        ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"]
    )
    jobs_raw = payload.get("jobs", [])
    jobs: list[JobState] = []
    for raw in jobs_raw:
        steps = tuple(
            JobStep(
                name=str(step.get("name") or ""),
                conclusion=str(step.get("conclusion") or ""),
            )
            for step in raw.get("steps", [])
            if isinstance(step, dict)
        )
        jobs.append(
            JobState(
                job_id=int(raw.get("id") or 0),
                name=str(raw.get("name") or "unknown"),
                conclusion=str(raw.get("conclusion") or "unknown"),
                steps=steps,
            )
        )
    return jobs


def _job_log(repo: str, run_id: str, job_id: int) -> str:
    result = subprocess.run(
        [
            "gh",
            "run",
            "view",
            run_id,
            "--repo",
            repo,
            "--job",
            str(job_id),
            "--log",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return "\n".join(
        part for part in (result.stdout.strip(), result.stderr.strip()) if part
    )


def _extract_root_buildx_error(log_text: str) -> str:
    patterns = (
        r"ERROR: failed to build: (?P<msg>.+)",
        r"#\d+ ERROR: (?P<msg>.+)",
        r"##\[error\]buildx failed with: (?P<msg>.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, log_text)
        if match:
            return re.sub(r"\s+", " ", match.group("msg")).strip()[:240]
    return "Unknown buildx failure (see job logs)."


def _classify_buildx_failure(message: str) -> str:
    lowered = message.lower()
    external_tokens = (
        "failed to parse error response",
        "invalid character '<' looking for beginning of value",
        "<!doctype html>",
        "502",
        "503",
        "504",
        "timeout",
        "connection reset",
        "unexpected eof",
        "tls handshake",
    )
    if any(token in lowered for token in external_tokens):
        return "likely external registry/buildx infrastructure failure"
    return "likely Dockerfile/application image build failure"


def _classify_coveralls_gate_failure(log_text: str) -> str | None:
    if "Coveralls - unified" not in log_text:
        return None
    lowered = log_text.lower()
    if "not found" in lowered or "timed out waiting for github status" in lowered:
        return "missing_or_delayed_external_status"
    if "failed for" in lowered or "state=failure" in lowered or "state=error" in lowered:
        return "reported_external_failure"
    return "external_status_gate_failure"


def _fetch_json(url: str) -> tuple[int, dict[str, Any], str | None]:
    try:
        with request.urlopen(url, timeout=10) as response:  # noqa: S310
            body = response.read().decode("utf-8")
            payload = json.loads(body)
            return response.status, payload if isinstance(payload, dict) else {}, None
    except error.HTTPError as exc:
        return exc.code, {}, str(exc)
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return 0, {}, str(exc)


def _health_snapshot(url: str) -> HealthSnapshot:
    status, payload, fetch_error = _fetch_json(url)
    git_sha = str(payload.get("git_sha") or payload.get("version") or "")
    raw_state = str(payload.get("status") or "").strip().lower()
    healthy_state = raw_state in {"", "healthy", "ok"}
    healthy = status == 200 and healthy_state and fetch_error is None
    return HealthSnapshot(
        url=url,
        http_status=status,
        healthy=healthy,
        git_sha=git_sha,
        error=fetch_error,
    )


def _branch_head_sha(repo: str, branch: str) -> str:
    payload = _gh_json(["gh", "api", f"repos/{repo}/commits/{branch}"])
    return str(payload.get("sha") or "")


def _find_job(jobs: list[JobState], name: str) -> JobState | None:
    for job in jobs:
        if job.name == name:
            return job
    return None


def format_ci_failure_diagnostics(repo: str, run_id: str) -> str:
    jobs = _load_run_jobs(repo, run_id)
    local_failures = [
        job.name
        for job in jobs
        if job.conclusion == "failure"
        and (
            job.name.startswith("Backend Tests")
            or job.name == "Frontend Build & Test"
            or job.name == "Lint"
            or job.name == "AC Traceability Check"
        )
    ]

    image_job = _find_job(jobs, "Build Staging Images")
    image_failure_line = "- Image build/push failures: `none`"
    if image_job is not None and image_job.conclusion == "failure":
        image_log = _job_log(repo, run_id, image_job.job_id)
        root_error = _extract_root_buildx_error(image_log)
        image_class = _classify_buildx_failure(root_error)
        image_failure_line = (
            "- Image build/push failures: "
            f"`{image_job.name}` → {image_class}; root error: `{root_error}`"
        )

    unified_job = _find_job(jobs, "Calculate Unified Coverage")
    external_failure_line = "- External status-gate failures: `none`"
    if unified_job is not None and unified_job.conclusion == "failure":
        unified_log = _job_log(repo, run_id, unified_job.job_id)
        coveralls_class = _classify_coveralls_gate_failure(unified_log)
        if coveralls_class is not None:
            external_failure_line = (
                "- External status-gate failures: "
                f"`Coveralls - unified` ({coveralls_class}); "
                "see https://github.com/wangzitian0/finance_report/issues/471"
            )

    local_line = (
        "- Local test/build failures: `none`"
        if not local_failures
        else f"- Local test/build failures: `{', '.join(local_failures)}`"
    )

    lines = [
        "## CI Failure Diagnostics",
        "",
        local_line,
        image_failure_line,
        external_failure_line,
    ]
    return "\n".join(lines) + "\n"


def _staging_blocked_before_vps(jobs: list[JobState]) -> bool:
    deploy_job = _find_job(jobs, "Build and Deploy")
    if deploy_job is None or deploy_job.conclusion != "failure":
        return False
    wait_step_failed = any(
        step.name == "Wait for matching CI success" and step.conclusion == "failure"
        for step in deploy_job.steps
    )
    deploy_step_skipped = any(
        step.name == "Deploy to Staging" and step.conclusion == "skipped"
        for step in deploy_job.steps
    )
    return wait_step_failed and deploy_step_skipped


def format_staging_staleness_diagnostics(
    *,
    repo: str,
    run_id: str,
    staging_health_url: str,
    production_health_url: str | None,
    main_branch: str,
) -> str:
    latest_main_sha = _branch_head_sha(repo, main_branch)
    latest_main_short = latest_main_sha[:7] if latest_main_sha else ""
    staging_health = _health_snapshot(staging_health_url)
    staging_sha_short = staging_health.git_sha[:7] if staging_health.git_sha else ""
    stale = bool(latest_main_short and staging_sha_short and latest_main_short != staging_sha_short)
    healthy_but_stale = staging_health.healthy and stale
    jobs = _load_run_jobs(repo, run_id)
    blocked_before_vps = _staging_blocked_before_vps(jobs)

    lines = [
        "## Staging Staleness Diagnostics",
        "",
        f"- Latest `main` SHA: `{latest_main_sha or 'unknown'}`",
        f"- Staging deployed SHA (`/api/health`): `{staging_health.git_sha or 'unknown'}`",
        f"- Staging health HTTP status: `{staging_health.http_status}`",
        f"- Staging health interpreted as healthy: `{staging_health.healthy}`",
        f"- healthy-but-stale: `{healthy_but_stale}`",
        (
            "- Deploy reached VPS/containers: `no` "
            "(blocked at `Wait for matching CI success`)"
            if blocked_before_vps
            else "- Deploy reached VPS/containers: `unknown_or_yes`"
        ),
    ]
    if staging_health.error:
        lines.append(f"- Staging health fetch error: `{staging_health.error}`")

    if production_health_url:
        production_health = _health_snapshot(production_health_url)
        lines.append(
            f"- Production deployed SHA (`/api/health`): `{production_health.git_sha or 'unknown'}`"
        )
        lines.append(f"- Production health HTTP status: `{production_health.http_status}`")
        if production_health.error:
            lines.append(f"- Production health fetch error: `{production_health.error}`")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Write workflow diagnostics summary")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--summary-path", type=Path, required=True)
    parser.add_argument("--mode", choices=("ci", "staging"), required=True)
    parser.add_argument("--staging-health-url")
    parser.add_argument("--production-health-url")
    parser.add_argument("--main-branch", default="main")
    args = parser.parse_args()

    if args.mode == "ci":
        summary = format_ci_failure_diagnostics(args.repo, args.run_id)
    else:
        if not args.staging_health_url:
            raise SystemExit("--staging-health-url is required in staging mode")
        summary = format_staging_staleness_diagnostics(
            repo=args.repo,
            run_id=args.run_id,
            staging_health_url=args.staging_health_url,
            production_health_url=args.production_health_url,
            main_branch=args.main_branch,
        )
    with args.summary_path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write(summary)
    print(f"Wrote workflow diagnostics summary to {args.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
