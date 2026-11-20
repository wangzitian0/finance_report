#!/usr/bin/env python3
"""Merge-time gate blocking PRs when unresolved review threads weigh >= 1.0."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

from common.meta.base.gate_cli import run_cli_command

SEVERITY_TAG = re.compile(r"\bseverity:\s*(high|middle|medium|low)\b", re.IGNORECASE)
SEVERITY_WEIGHTS: dict[str, tuple[str, float]] = {
    "high": ("High", 1.0),
    "middle": ("Medium", 0.5),
    "medium": ("Medium", 0.5),
    "low": ("Low", 0.25),
}
UNLABELLED_WEIGHT: tuple[str, float] = ("Medium (default)", 0.5)
REVIEW_BLOCK_SCORE = 1.0
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


def _first_comment(thread: dict[str, Any]) -> dict[str, Any]:
    """Return the first comment node of a thread, or an empty dict."""
    nodes = (thread.get("comments") or {}).get("nodes") or []
    return nodes[0] if nodes else {}


def thread_weight(thread: dict[str, Any]) -> tuple[str, float]:
    """Return (label, weight) from the first comment's literal severity tag."""
    body = _first_comment(thread).get("body") or ""
    if match := SEVERITY_TAG.search(body):
        return SEVERITY_WEIGHTS[match.group(1).lower()]
    return UNLABELLED_WEIGHT


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
    """Fetch ALL review threads via `gh api graphql` (the real, network seam)."""
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
    """Evaluate the weighted review gate. Return 0 (pass/skip) or 1 (block)."""
    if pr_number is None:
        print(
            "PR review thread gate: no PR number (non-PR event); skipping.",
            file=sys.stderr,
        )
        return 0

    payload = fetch_threads(pr_number, repo)
    nodes = _thread_nodes(payload)

    unresolved: list[tuple[dict[str, Any], str, float]] = []
    for thread in nodes:
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        label, weight = thread_weight(thread)
        unresolved.append((thread, label, weight))

    score = sum(weight for _, _, weight in unresolved)
    total = len(nodes)
    print(
        f"PR review thread gate (PR #{pr_number}, {repo}): "
        f"{total} thread(s); {len(unresolved)} unresolved, weighted score {score:.2f} "
        f"(blocks at >= {REVIEW_BLOCK_SCORE:.2f})."
    )

    if score >= REVIEW_BLOCK_SCORE:
        print(
            f"BLOCKED: unresolved review score {score:.2f} >= {REVIEW_BLOCK_SCORE:.2f}; resolve threads before merge:",
            file=sys.stderr,
        )
        for thread, label, weight in unresolved:
            body = (_first_comment(thread).get("body") or "").strip().splitlines()
            snippet = body[0] if body else ""
            print(
                f"  - [{label} {weight:.2f}] {_thread_url(thread)} :: {snippet}",
                file=sys.stderr,
            )
        return 1

    for thread, label, weight in unresolved:
        body = (_first_comment(thread).get("body") or "").strip().splitlines()
        snippet = body[0] if body else ""
        print(
            f"  [report] non-blocking unresolved [{label} {weight:.2f}]: {_thread_url(thread)} :: {snippet}"
        )

    print(f"PR review thread gate OK: score {score:.2f} < {REVIEW_BLOCK_SCORE:.2f}.")
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


def _main(argv: Sequence[str] | None = None) -> int:
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
            "PR review thread gate: a PR number was supplied but the repo could "
            "not be resolved (--repo / $GITHUB_REPOSITORY); failing closed.",
            file=sys.stderr,
        )
        return 1

    return run(pr_number, repo, fetch_threads=fetch_threads)


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli_command(_main, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
