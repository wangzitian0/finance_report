#!/usr/bin/env python3
"""Merge-time gate that blocks unresolved P0/P1 PR review threads.

This contract supports issue #755 (scope 2a): a PR must not merge while a
high-severity review thread is still open. It fetches the PR's review threads
via the GitHub GraphQL API (`gh api graphql`), classifies each thread's
severity from documented markers, and exits non-zero when any *unresolved*
thread is classified blocking (P0/P1).

Severity classification rule (documented in ``docs/ssot/ci-cd.md`` — keep both
in sync). A thread is **BLOCKING** (P0/P1) when the first comment body matches
the marker regex ``\\b(P0|P1)\\b`` (case-insensitive) OR the first comment is
Copilot-authored AND it is not explicitly marked a lower severity (its body
contains ``P2``/``P3``/``nit``). Everything else is **LOWER** severity.

Decision: exit 1 if any thread is *unresolved* AND classified BLOCKING.
Resolved or outdated threads never block. Lower-severity unresolved threads are
printed (reported) but do NOT block. The gate is bootstrap-safe: a fresh PR
with no unresolved P0/P1 passes, and a non-PR invocation (no PR number) skips
cleanly with exit 0.

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
from collections.abc import Callable
from typing import Any

# Authors whose review threads are treated as blocking by default. GitHub has
# spelled the Copilot reviewer login differently over time; cover the known
# variants (compared case-insensitively).
COPILOT_AUTHORS: frozenset[str] = frozenset(
    {
        "copilot",
        "github-copilot[bot]",
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
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
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


def _thread_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract reviewThreads nodes from the GraphQL envelope, defensively."""
    repo = ((payload or {}).get("data") or {}).get("repository") or {}
    pr = repo.get("pullRequest") or {}
    return (pr.get("reviewThreads") or {}).get("nodes") or []


def fetch_threads(pr_number: int, repo: str) -> dict[str, Any]:
    """Fetch review threads via `gh api graphql` (the real, network seam).

    ``repo`` is ``owner/name``. Returns the parsed JSON envelope. This function
    is patched/replaced in tests so no network call is made there.
    """
    owner, _, name = repo.partition("/")
    result = subprocess.run(
        [
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
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


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
        print(f"  [report] lower-severity unresolved: {_thread_url(thread)} :: {snippet}")

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


def main(argv: list[str] | None = None) -> int:
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
        print(
            "PR review thread gate: a PR number was supplied but no repo (--repo / $GITHUB_REPOSITORY); skipping.",
            file=sys.stderr,
        )
        return 0

    # Bind through the module attribute so tests can monkeypatch fetch_threads.
    return run(pr_number, repo, fetch_threads=fetch_threads)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
