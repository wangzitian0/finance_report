#!/usr/bin/env python3
"""Verify release evidence before production dry-run or deployment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable

JsonValue = object
GhJson = Callable[[list[str]], JsonValue]


def _default_gh_json(args: list[str]) -> JsonValue:
    return json.loads(subprocess.check_output(args, text=True))


def _write_github_output(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            print(f"{key}={value}", file=fh)


def _require_list(value: JsonValue, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise RuntimeError(f"{label}: expected a JSON list")
    if not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"{label}: expected a JSON list of objects")
    return value


def _require_jobs(value: JsonValue, run_id: str) -> list[dict[str, object]]:
    if not isinstance(value, dict):
        raise RuntimeError(f"staging run {run_id}: expected a JSON object")
    jobs = value.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        raise RuntimeError(f"staging run {run_id}: expected jobs list")
    return jobs


def verify_source_ci(
    *, repository: str, release_sha: str, gh_json: GhJson = _default_gh_json
) -> str:
    runs = _require_list(
        gh_json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                "ci.yml",
                "--commit",
                release_sha,
                "--limit",
                "30",
                "--json",
                "databaseId,status,conclusion,event,headBranch",
            ]
        ),
        "source CI runs",
    )
    for run in runs:
        if (
            run.get("event") == "push"
            and run.get("headBranch") == "main"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
        ):
            return str(run["databaseId"])
    raise RuntimeError(f"No successful main CI run found for {release_sha}")


def verify_release_images_run(
    *, repository: str, release_sha: str, gh_json: GhJson = _default_gh_json
) -> str:
    runs = _require_list(
        gh_json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                "release-images.yml",
                "--commit",
                release_sha,
                "--limit",
                "30",
                "--json",
                "databaseId,status,conclusion,event",
            ]
        ),
        "release-images runs",
    )
    for run in runs:
        if (
            run.get("event") == "push"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
        ):
            return str(run["databaseId"])
    raise RuntimeError(f"No successful release-images.yml run found for {release_sha}")


def verify_staging(
    *, repository: str, version_ref: str, gh_json: GhJson = _default_gh_json
) -> str:
    runs = _require_list(
        gh_json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                "staging-deploy.yml",
                "--limit",
                "50",
                "--json",
                "databaseId,status,displayTitle,url",
            ]
        ),
        "staging runs",
    )
    expected_title = f"Deploy Staging {version_ref}"
    candidate_run_ids = [
        str(run["databaseId"])
        for run in runs
        if run.get("status") == "completed"
        and run.get("displayTitle") == expected_title
    ]
    if not candidate_run_ids:
        raise RuntimeError(
            "No completed Deploy Staging run found for "
            f"{version_ref}. Run staging-deploy.yml for this version_ref first."
        )

    required_staging_jobs = {"Deploy Staging", "Staging Provider Gate"}
    optional_staging_jobs = {"Staging AI/OCR Gate"}
    for candidate_run_id in candidate_run_ids:
        jobs = _require_jobs(
            gh_json(
                [
                    "gh",
                    "run",
                    "view",
                    candidate_run_id,
                    "--repo",
                    repository,
                    "--json",
                    "jobs",
                ]
            ),
            candidate_run_id,
        )
        by_name = {job.get("name"): job for job in jobs}
        missing = sorted(required_staging_jobs - set(by_name))
        failed = sorted(
            name
            for name in required_staging_jobs
            if name in by_name and by_name[name].get("conclusion") != "success"
        )
        if missing or failed:
            print(
                "::notice::Skipping staging run "
                f"{candidate_run_id}: release-critical jobs "
                f"missing={missing} failed={failed}"
            )
            continue
        for name in sorted(optional_staging_jobs):
            job = by_name.get(name)
            if job and job.get("conclusion") != "success":
                print(
                    f"::warning::{name} concluded {job.get('conclusion')}; "
                    "it does not block production release eligibility."
                )
        return candidate_run_id

    raise RuntimeError(
        "No completed Deploy Staging run found for "
        f"{version_ref} with successful release-critical jobs. "
        "Rerun staging-deploy.yml for this version_ref first."
    )


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        choices=("source-ci", "release-images-run", "staging"),
        required=True,
    )
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--release-sha", default=os.getenv("RELEASE_SHA", ""))
    parser.add_argument("--version-ref", default=os.getenv("VERSION_REF", ""))
    args = parser.parse_args(argv)

    try:
        repository = _required(args.repository, "repository")
        if args.check == "source-ci":
            run_id = verify_source_ci(
                repository=repository,
                release_sha=_required(args.release_sha, "release-sha"),
            )
        elif args.check == "release-images-run":
            run_id = verify_release_images_run(
                repository=repository,
                release_sha=_required(args.release_sha, "release-sha"),
            )
        else:
            run_id = verify_staging(
                repository=repository,
                version_ref=_required(args.version_ref, "version-ref"),
            )
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"verify_release_evidence failed: {exc}", file=sys.stderr)
        return 1

    _write_github_output({"run_id": run_id})
    print(f"Release evidence OK: check={args.check} run_id={run_id}")
    return 0
