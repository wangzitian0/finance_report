#!/usr/bin/env python3
"""Merge-time gate that blocks unresolved P0/P1 PR review threads.

This contract supports issue #755 (scope 2a): a PR must not merge while a
high-severity review thread is still open. It fetches the PR's review threads
via the GitHub GraphQL API (`gh api graphql`), classifies each thread's
severity from documented markers, and exits non-zero when any *unresolved*
thread is classified blocking (P0/P1).

Severity classification rule (documented in ``common/testing/ci-cd.md`` — keep both
in sync). A thread is **BLOCKING** (P0/P1) when the first comment body matches
the marker regex ``\\b(P0|P1)\\b`` (case-insensitive) OR the first comment is
Copilot-authored AND it is not explicitly marked a lower severity (its body
contains ``P2``/``P3``/``nit``). Everything else is **LOWER** severity.

Decision: exit 1 if any thread is *unresolved* AND classified BLOCKING.
Resolved or outdated threads never block. Lower-severity unresolved threads are
printed (reported) but do NOT block. The gate is bootstrap-safe: a fresh PR
with no unresolved P0/P1 passes, and a non-PR invocation (no PR number) skips
cleanly with exit 0.

Fail-closed semantics: :func:`fetch_threads` paginates until
``pageInfo.hasNextPage`` is false (so a PR with >100 review threads cannot hide
a blocking thread beyond the first page), and raises rather than silently
truncating if a page is missing its cursor. When a PR number is supplied but
the repo cannot be resolved (a likely CI misconfiguration), :func:`main`
exits 1 instead of skipping, so the merge gate is never silently disabled.

The GraphQL call is isolated behind the :func:`fetch_threads` seam so tests can
inject canned JSON without any network access.
"""

from __future__ import annotations

import argparse
import enum
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

from common.meta.base.gate_cli import run_gate

# Authors whose review threads are treated as blocking by default. GitHub has
# spelled the Copilot reviewer login differently over time; cover the known
# variants (compared case-insensitively). "copilot-pull-request-reviewer"
# (no "[bot]" suffix) is the actual login the GraphQL reviewThreads API
# returns today (confirmed 2026-07-12 against real threads on #1776/#1782/
# #1786) -- the "[bot]"-suffixed form was never observed in the wild and this
# gate silently misclassified every real Copilot thread as non-blocking
# until this was added. Kept both forms since REST/GraphQL or a future
# GitHub-side change could plausibly use either.
COPILOT_AUTHORS: frozenset[str] = frozenset(
    {
        "copilot",
        "github-copilot[bot]",
        "copilot-pull-request-reviewer",
        "copilot-pull-request-reviewer[bot]",
    }
)

# Explicit high-severity markers. Word-boundary, case-insensitive.
BLOCKING_MARKER = re.compile(r"\b(P0|P1)\b", re.IGNORECASE)

# Explicit lower-severity markers. A Copilot thread carrying one of these is
# treated as lower severity instead of the Copilot default.
LOWER_MARKER = re.compile(r"\b(P2|P3|nit)\b", re.IGNORECASE)

# A fetcher takes (pr_number, repo) and returns the parsed `gh api graphql`
# JSON envelope.
FetchThreads = Callable[[int, str], dict[str, Any]]

_GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          isResolved
          isOutdated
          comments(first: 1) {
            nodes {
              body
              url
              author { login }
            }
          }
        }
      }
    }
  }
}
"""

# Hard ceiling on pagination so a pathological PR cannot loop forever; 100
# pages * 100 threads/page = 10k threads, far beyond any real PR.
_MAX_PAGES = 100


class Severity(enum.Enum):
    """Severity classes for a review thread."""

    BLOCKING = "blocking"  # P0/P1 (or Copilot default)
    LOWER = "lower"  # P2/P3/nit/plain comment


def _first_comment(thread: dict[str, Any]) -> dict[str, Any]:
    """Return the first comment node of a thread, or an empty dict."""
    nodes = (thread.get("comments") or {}).get("nodes") or []
    return nodes[0] if nodes else {}


def _comment_author(comment: dict[str, Any]) -> str:
    return ((comment.get("author") or {}).get("login") or "").strip()


def classify_thread(thread: dict[str, Any]) -> Severity:
    """Classify a review thread's severity from its first comment.

    See module docstring for the exact, documented rule.
    """
    comment = _first_comment(thread)
    body = comment.get("body") or ""
    author = _comment_author(comment).lower()

    if BLOCKING_MARKER.search(body):
        return Severity.BLOCKING

    if author in COPILOT_AUTHORS and not LOWER_MARKER.search(body):
        return Severity.BLOCKING

    return Severity.LOWER


def _thread_url(thread: dict[str, Any]) -> str:
    return _first_comment(thread).get("url") or "(no url)"


def _review_threads(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the reviewThreads object from one GraphQL page, defensively."""
    repo = ((payload or {}).get("data") or {}).get("repository") or {}
    pr = repo.get("pullRequest") or {}
    return pr.get("reviewThreads") or {}


def _thread_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract reviewThreads nodes from the GraphQL envelope, defensively."""
    return _review_threads(payload).get("nodes") or []


def _wrap_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap merged thread nodes back into the standard GraphQL envelope shape."""
    return {
        "data": {
            "repository": {
                "pullRequest": {"reviewThreads": {"nodes": nodes}},
            }
        }
    }


def _graphql_page(
    owner: str, name: str, pr_number: int, after: str | None
) -> dict[str, Any]:
    """Run one `gh api graphql` page request and return the parsed JSON."""
    cmd = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={_GRAPHQL_QUERY}",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"number={pr_number}",
    ]
    if after:
        cmd += ["-F", f"after={after}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def fetch_threads(pr_number: int, repo: str) -> dict[str, Any]:
    """Fetch ALL review threads via `gh api graphql` (the real, network seam).

    Paginates through `reviewThreads` until `pageInfo.hasNextPage` is false, so
    a PR with more than 100 review threads cannot let unresolved blocking
    threads beyond the first page slip past the merge gate. Returns a single
    merged JSON envelope. This function is patched/replaced in tests so no
    network call is made there.
    """
    owner, _, name = repo.partition("/")
    all_nodes: list[dict[str, Any]] = []
    after: str | None = None
    for _ in range(_MAX_PAGES):
        payload = _graphql_page(owner, name, pr_number, after)
        threads = _review_threads(payload)
        all_nodes.extend(threads.get("nodes") or [])
        page_info = threads.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return _wrap_nodes(all_nodes)
        after = page_info.get("endCursor")
        if not after:
            # hasNextPage is true but no cursor: cannot safely continue. Fail
            # closed rather than silently dropping later pages.
            raise RuntimeError(
                "PR review thread gate: GraphQL reported more pages but no "
                "endCursor; cannot guarantee all threads were read."
            )
    raise RuntimeError(
        f"PR review thread gate: exceeded the page limit ({_MAX_PAGES}) while reading review threads; failing closed."
    )


def run(
    pr_number: int | None,
    repo: str,
    fetch_threads: FetchThreads = fetch_threads,
) -> int:
    """Evaluate the gate. Return 0 (pass/skip) or 1 (block).

    Skips cleanly (exit 0, no fetch) when ``pr_number`` is None — e.g. a
    non-pull_request workflow event.
    """
    if pr_number is None:
        print(
            "PR review thread gate: no PR number (non-PR event); skipping.",
            file=sys.stderr,
        )
        return 0

    payload = fetch_threads(pr_number, repo)
    nodes = _thread_nodes(payload)

    blocking: list[dict[str, Any]] = []
    lower_unresolved: list[dict[str, Any]] = []

    for thread in nodes:
        if thread.get("isResolved"):
            continue  # resolved threads never block
        if thread.get("isOutdated"):
            continue  # outdated threads never block
        severity = classify_thread(thread)
        if severity is Severity.BLOCKING:
            blocking.append(thread)
        else:
            lower_unresolved.append(thread)

    total = len(nodes)
    print(
        f"PR review thread gate (PR #{pr_number}, {repo}): "
        f"{total} thread(s); {len(blocking)} unresolved blocking (P0/P1), "
        f"{len(lower_unresolved)} unresolved lower-severity (reported, "
        f"non-blocking)."
    )

    for thread in lower_unresolved:
        body = (_first_comment(thread).get("body") or "").strip().splitlines()
        snippet = body[0] if body else ""
        print(
            f"  [report] lower-severity unresolved: {_thread_url(thread)} :: {snippet}"
        )

    if blocking:
        print(
            "BLOCKED: unresolved P0/P1 (or Copilot) review thread(s) must be resolved before merge:",
            file=sys.stderr,
        )
        for thread in blocking:
            body = (_first_comment(thread).get("body") or "").strip().splitlines()
            snippet = body[0] if body else ""
            print(
                f"  - {_thread_url(thread)} :: {snippet}",
                file=sys.stderr,
            )
        return 1

    print("PR review thread gate OK: no unresolved P0/P1 review threads.")
    return 0


def _resolve_pr_number(arg_value: int | None) -> int | None:
    """PR number from --pr-number, else $PR_NUMBER env, else None."""
    if arg_value is not None:
        return arg_value
    env_value = os.environ.get("PR_NUMBER", "").strip()
    if not env_value or env_value.lower() in {"none", "null"}:
        return None
    try:
        return int(env_value)
    except ValueError:
        return None


def _resolve_repo(arg_value: str | None) -> str:
    """Repo (owner/name) from --repo, else $GITHUB_REPOSITORY."""
    return (arg_value or os.environ.get("GITHUB_REPOSITORY") or "").strip()


def _run_command(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pr-number",
        type=int,
        default=None,
        help="PR number (defaults to $PR_NUMBER; skips cleanly if absent).",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository as owner/name (defaults to $GITHUB_REPOSITORY).",
    )
    args = parser.parse_args(argv)

    pr_number = _resolve_pr_number(args.pr_number)
    repo = _resolve_repo(args.repo)

    if pr_number is not None and not repo:
        # A PR number is present but the repo cannot be resolved — almost
        # certainly a CI misconfiguration (e.g. a typo'd env var). Fail closed
        # rather than silently disabling a merge-blocking contract.
        print(
            "PR review thread gate: a PR number was supplied but the repo could "
            "not be resolved (--repo / $GITHUB_REPOSITORY); failing closed.",
            file=sys.stderr,
        )
        return 1

    # Bind through the module attribute so tests can monkeypatch fetch_threads.
    return run(pr_number, repo, fetch_threads=fetch_threads)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "PR-REVIEW-THREADS", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
