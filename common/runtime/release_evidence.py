#!/usr/bin/env python3
"""Verify release evidence before production dry-run or deployment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence

from common.runtime.github_api import write_github_output as _write_github_output

JsonValue = object
GhJson = Callable[[list[str]], JsonValue]


def _default_gh_json(args: list[str]) -> JsonValue:
    return json.loads(subprocess.check_output(args, text=True))


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
                "deploy.yml",
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
    raise RuntimeError(f"No successful deploy.yml run found for {release_sha}")


def verify_staging(
    *,
    repository: str,
    version_ref: str,
    release_sha: str,
    gh_json: GhJson = _default_gh_json,
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
                "deploy.yml",
                "--limit",
                "50",
                "--json",
                "databaseId,status,displayTitle,url,headSha",
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
        and run.get("headSha") == release_sha
    ]
    if not candidate_run_ids:
        raise RuntimeError(
            "No completed Deploy Staging run found for "
            f"{version_ref}. Run deploy.yml for this version_ref first."
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
        "Rerun deploy.yml for this version_ref first."
    )


def verify_reviewed_change(
    *, repository: str, release_sha: str, gh_json: GhJson = _default_gh_json
) -> str:
    pulls = _require_list(
        gh_json(
            [
                "gh",
                "api",
                f"repos/{repository}/commits/{release_sha}/pulls",
                "--header",
                "Accept: application/vnd.github+json",
            ]
        ),
        "reviewed changes",
    )
    for pull in pulls:
        base = pull.get("base")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        if (
            pull.get("state") == "closed"
            and pull.get("merged_at")
            and pull.get("merge_commit_sha") == release_sha
            and isinstance(base, dict)
            and base.get("ref") == "main"
            and isinstance(base_repo, dict)
            and base_repo.get("full_name") == repository
        ):
            url = pull.get("html_url")
            if isinstance(url, str) and url == (
                f"https://github.com/{repository}/pull/{pull.get('number')}"
            ):
                return url
    raise RuntimeError(
        f"No merged main-branch pull request found for release SHA {release_sha}"
    )


def verify_real_corpus_eval(
    *,
    repository: str,
    max_age_hours: float = 48.0,
    gh_json: GhJson = _default_gh_json,
    now: object = None,
) -> str:
    """Verify the most recent real-corpus evaluation (#1764) is fresh and green.

    Unlike the other three checks, this is deliberately NOT tied to a specific
    ``release_sha``: the real-document corpus changes on its own operator
    cadence (real PDFs are never committed — RL-6 — and provider quota is
    finite), not on every commit. A stale-or-red run fails closed (Axiom E: an
    unrun/expired check reads as unproven, never as a silent pass) — this is
    the enforcement half of #1764's G-enforcement guarantee.

    ``now`` is DI-injected the same way ``gh_json`` is, so the freshness
    comparison is testable without depending on wall-clock time.
    """
    import datetime as _dt

    current_time = (
        now if isinstance(now, _dt.datetime) else _dt.datetime.now(_dt.timezone.utc)
    )

    def parsed_created_at(run: dict[str, object]) -> _dt.datetime | None:
        raw = run.get("createdAt")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    runs = _require_list(
        gh_json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                "real-corpus-eval.yml",
                # #1764 CR follow-up: 5 was too tight -- a burst of queued/
                # in-progress runs could push every completed run outside the
                # window, false-failing this check even though an older
                # completed run exists. 20 is a cheap, generous margin for a
                # workflow expected to run on an infrequent (scheduled) cadence.
                "--limit",
                "20",
                "--json",
                "databaseId,status,conclusion,createdAt",
            ]
        ),
        "real-corpus-eval runs",
    )
    completed = [run for run in runs if run.get("status") == "completed"]
    if not completed:
        raise RuntimeError(
            "No completed real-corpus-eval run found. Run "
            "`tools/reverify_real_corpus.py` against the operator's real "
            "document corpus and record the result first."
        )

    # #1764 CR follow-up: a completed run with a missing/malformed createdAt
    # cannot be safely excluded from "most recent" ordering either -- it
    # might BE the actual latest run, just with bad timestamp data. Fail
    # closed here rather than silently ranking it last (below every
    # valid-timestamped run) and picking an older run in its place, which
    # would quietly violate "the most recent completed run governs".
    unparseable = [run for run in completed if parsed_created_at(run) is None]
    if unparseable:
        raise RuntimeError(
            f"real-corpus-eval run {unparseable[0].get('databaseId')} is "
            "missing createdAt (or it is malformed) — cannot reliably "
            "determine the most recent completed run among multiple "
            "candidates."
        )

    # explicitly select by createdAt instead of assuming gh run list's own
    # ordering already puts the most recent completed run first -- that
    # assumption held but was never enforced by this code.
    latest = max(completed, key=parsed_created_at)
    conclusion = latest.get("conclusion")
    if conclusion != "success":
        raise RuntimeError(
            f"Latest real-corpus-eval run {latest.get('databaseId')} did not "
            f"succeed (conclusion={conclusion!r}) — a real-document accuracy "
            "or calibration regression was found."
        )

    # createdAt is already known-valid for every completed run (checked
    # above), including `latest` -- no need to re-validate it here.
    created_at = parsed_created_at(latest)
    assert created_at is not None
    age_hours = (current_time - created_at).total_seconds() / 3600.0
    if age_hours > max_age_hours:
        raise RuntimeError(
            f"Latest real-corpus-eval run {latest.get('databaseId')} is stale "
            f"({age_hours:.1f}h old, max {max_age_hours}h) — re-run the "
            "evaluation before releasing."
        )

    return str(latest["databaseId"])


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        choices=(
            "source-ci",
            "release-images-run",
            "staging",
            "reviewed-change",
            "real-corpus-eval",
        ),
        required=True,
    )
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--release-sha", default=os.getenv("RELEASE_SHA", ""))
    parser.add_argument("--version-ref", default=os.getenv("VERSION_REF", ""))
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=48.0,
        help="real-corpus-eval only: how stale the latest run may be before this fails.",
    )
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
        elif args.check == "real-corpus-eval":
            run_id = verify_real_corpus_eval(
                repository=repository,
                max_age_hours=args.max_age_hours,
            )
            outputs = {"run_id": run_id}
        elif args.check == "staging":
            run_id = verify_staging(
                repository=repository,
                version_ref=_required(args.version_ref, "version-ref"),
                release_sha=_required(args.release_sha, "release-sha"),
            )
            outputs = {"run_id": run_id}
        else:
            reviewed_change_url = verify_reviewed_change(
                repository=repository,
                release_sha=_required(args.release_sha, "release-sha"),
            )
            outputs = {"reviewed_change_url": reviewed_change_url}
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"verify_release_evidence failed: {exc}", file=sys.stderr)
        return 1

    if args.check in ("source-ci", "release-images-run"):
        outputs = {"run_id": run_id}
    _write_github_output(outputs)
    rendered = " ".join(f"{key}={value}" for key, value in outputs.items())
    print(f"Release evidence OK: check={args.check} {rendered}")
    return 0
