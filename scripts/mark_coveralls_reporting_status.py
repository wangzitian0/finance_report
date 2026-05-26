#!/usr/bin/env python3
"""Mark Coveralls status contexts as reporting-only after local gates pass."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass


DEFAULT_CONTEXTS = (
    "coverage/coveralls",
    "coverage/coveralls (push)",
    "Coveralls - unified",
    "Coveralls - backend",
    "Coveralls - frontend",
)
DEFAULT_WAIT_CONTEXTS = (
    "coverage/coveralls",
    "Coveralls - unified",
    "Coveralls - backend",
    "Coveralls - frontend",
)
DEFAULT_DESCRIPTION = "Coveralls reporting-only; local coverage gate passed."
DEFAULT_SETTLE_SECONDS = 45
TERMINAL_STATES = {"success", "failure", "error"}


@dataclass(frozen=True)
class GitHubCommitStatus:
    context: str
    state: str
    description: str | None
    target_url: str | None


def _log(message: str) -> None:
    print(message, flush=True)


def _run_gh_json(args: list[str]) -> dict[str, object]:
    result = subprocess.run(
        ["gh", "api", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"gh api failed: {detail}")
    return json.loads(result.stdout or "{}")


def _run_gh_status_create(
    *,
    repo: str,
    sha: str,
    context: str,
    description: str,
    target_url: str,
) -> None:
    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repo}/statuses/{sha}",
            "-f",
            "state=success",
            "-f",
            f"context={context}",
            "-f",
            f"description={description}",
            "-f",
            f"target_url={target_url}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"failed to create GitHub status: {detail}")


def fetch_commit_statuses(repo: str, sha: str) -> list[GitHubCommitStatus]:
    payload = _run_gh_json([f"repos/{repo}/commits/{sha}/status"])
    statuses = payload.get("statuses", [])
    if not isinstance(statuses, list):
        raise RuntimeError("GitHub commit status response did not contain a list")

    parsed: list[GitHubCommitStatus] = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        parsed.append(
            GitHubCommitStatus(
                context=str(status.get("context", "")),
                state=str(status.get("state", "")),
                description=status.get("description"),
                target_url=status.get("target_url"),
            )
        )
    return parsed


def latest_status_for_context(
    statuses: list[GitHubCommitStatus],
    context: str,
) -> GitHubCommitStatus | None:
    for status in statuses:
        if status.context == context:
            return status
    return None


def is_coveralls_context(context: str) -> bool:
    return (
        context == "coverage/coveralls"
        or context.startswith("coverage/coveralls ")
        or context.startswith("Coveralls")
    )


def coveralls_contexts_from_statuses(
    statuses: list[GitHubCommitStatus],
) -> tuple[str, ...]:
    contexts: list[str] = []
    for status in statuses:
        if is_coveralls_context(status.context) and status.context not in contexts:
            contexts.append(status.context)
    return tuple(contexts)


def add_discovered_coveralls_contexts(
    observed: dict[str, GitHubCommitStatus | None],
    statuses: list[GitHubCommitStatus],
) -> None:
    for context in coveralls_contexts_from_statuses(statuses):
        observed.setdefault(context, None)


def observe_terminal_coveralls_statuses(
    observed: dict[str, GitHubCommitStatus | None],
    statuses: list[GitHubCommitStatus],
) -> None:
    add_discovered_coveralls_contexts(observed, statuses)
    for context in tuple(observed):
        if observed[context] is not None:
            continue
        status = latest_status_for_context(statuses, context)
        if status is not None and status.state in TERMINAL_STATES:
            observed[context] = status
            _log(
                f"Observed {context!r}: state={status.state} "
                f"description={status.description!r} url={status.target_url}"
            )


def wait_for_coveralls_observations(
    *,
    repo: str,
    sha: str,
    contexts: tuple[str, ...] = DEFAULT_WAIT_CONTEXTS,
    timeout_seconds: int = 120,
    poll_seconds: int = 5,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict[str, GitHubCommitStatus | None]:
    """Wait briefly for Coveralls to write its asynchronous status contexts."""
    deadline = monotonic() + timeout_seconds
    observed: dict[str, GitHubCommitStatus | None] = {
        context: None for context in contexts
    }
    required_contexts = tuple(contexts)

    while True:
        statuses = fetch_commit_statuses(repo, sha)
        observe_terminal_coveralls_statuses(observed, statuses)

        if all(observed[context] is not None for context in required_contexts):
            return observed

        if monotonic() >= deadline:
            missing = [
                context for context in required_contexts if observed[context] is None
            ]
            _log(
                f"Did not observe terminal Coveralls statuses on {sha}: "
                f"{', '.join(missing)}; "
                "publishing local reporting-only status."
            )
            return observed

        missing = [
            context for context in required_contexts if observed[context] is None
        ]
        _log(f"Waiting for Coveralls statuses on {sha}: {', '.join(missing)}")
        sleep(poll_seconds)


def mark_coveralls_reporting_only(
    *,
    repo: str,
    sha: str,
    target_url: str,
    contexts: tuple[str, ...] = DEFAULT_CONTEXTS,
    wait_contexts: tuple[str, ...] = DEFAULT_WAIT_CONTEXTS,
    description: str = DEFAULT_DESCRIPTION,
    timeout_seconds: int = 120,
    poll_seconds: int = 5,
    settle_seconds: int = DEFAULT_SETTLE_SECONDS,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict[str, GitHubCommitStatus | None]:
    """Publish final success statuses for Coveralls reporting-only contexts."""
    observed = wait_for_coveralls_observations(
        repo=repo,
        sha=sha,
        contexts=wait_contexts,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    publish_contexts = tuple(contexts) + tuple(
        context for context in observed if context not in contexts
    )
    for context in publish_contexts:
        observed.setdefault(context, None)
    for context in publish_contexts:
        _run_gh_status_create(
            repo=repo,
            sha=sha,
            context=context,
            description=description,
            target_url=target_url,
        )
        _log(f"Published reporting-only success for {context!r} on {sha}")
    if settle_seconds > 0:
        _log(f"Settling for {settle_seconds}s before final Coveralls status check")
        sleep(settle_seconds)
        latest_statuses = fetch_commit_statuses(repo, sha)
        for context in coveralls_contexts_from_statuses(latest_statuses):
            if context not in publish_contexts:
                publish_contexts = (*publish_contexts, context)
        stale_contexts: list[str] = []
        for context in publish_contexts:
            latest = latest_status_for_context(latest_statuses, context)
            if (
                latest is None
                or latest.state != "success"
                or latest.description != description
                or latest.target_url != target_url
            ):
                stale_contexts.append(context)

        for context in stale_contexts:
            _run_gh_status_create(
                repo=repo,
                sha=sha,
                context=context,
                description=description,
                target_url=target_url,
            )
            _log(f"Re-published final reporting-only success for {context!r} on {sha}")
        assert_coveralls_statuses_reporting_only(
            repo=repo,
            sha=sha,
            target_url=target_url,
            description=description,
        )
    return observed


def assert_coveralls_statuses_reporting_only(
    *,
    repo: str,
    sha: str,
    target_url: str,
    description: str,
) -> None:
    latest_statuses = fetch_commit_statuses(repo, sha)
    unexpected: list[str] = []
    for context in coveralls_contexts_from_statuses(latest_statuses):
        latest = latest_status_for_context(latest_statuses, context)
        if latest is None:
            continue
        if (
            latest.state != "success"
            or latest.description != description
            or latest.target_url != target_url
        ):
            unexpected.append(
                f"{context} state={latest.state} "
                f"description={latest.description!r} url={latest.target_url}"
            )
    if unexpected:
        raise RuntimeError(
            "Coveralls reporting-only normalization did not settle: "
            + "; ".join(unexpected)
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Wait for Coveralls statuses, then publish local reporting-only "
            "success statuses for the same contexts."
        )
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument(
        "--context",
        action="append",
        dest="contexts",
        help=(
            "Coveralls status context to normalize. May be specified multiple "
            "times. Defaults to all known Coveralls contexts."
        ),
    )
    parser.add_argument(
        "--wait-context",
        action="append",
        dest="wait_contexts",
        help=(
            "Coveralls status context to wait for before publishing reporting-only "
            "success. Defaults to stable Coveralls contexts; optional contexts are "
            "normalized without blocking when absent."
        ),
    )
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--settle-seconds", type=int, default=DEFAULT_SETTLE_SECONDS)
    args = parser.parse_args()

    try:
        mark_coveralls_reporting_only(
            repo=args.repo,
            sha=args.sha,
            target_url=args.target_url,
            contexts=tuple(args.contexts or DEFAULT_CONTEXTS),
            wait_contexts=tuple(args.wait_contexts or DEFAULT_WAIT_CONTEXTS),
            description=args.description,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            settle_seconds=args.settle_seconds,
        )
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(
            f"::error title=Coveralls reporting status override failed::{exc}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
