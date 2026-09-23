#!/usr/bin/env python3
"""Open or update the unified coverage baseline PR on main branch rise (#1811).

In dry-run mode, rehearses the rise merge calculation and side-effect parameters
without switching branches, committing, pushing, or invoking GitHub PR commands.
This enables pre-main rehearsal during PR CI without side effects.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE_BRANCH = "automation/unified-coverage-baseline"
DEFAULT_BASELINE_FILE = "unified-coverage.json"


def calculate_rise_merge(
    old_data: dict[str, Any],
    new_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[float | None, float]], list[str]]:
    """Perform a quantized rise-only merge between old and new coverage summaries."""

    def pct(d: dict[str, Any]) -> float:
        return round(float(d.get("coverage_percent", 0.0)), 2)

    merged = dict(new_data)
    merged["breakdown"] = dict(new_data.get("breakdown", {}))
    rises: dict[str, tuple[float | None, float]] = {}
    kept: list[str] = []

    for name, comp in list(merged["breakdown"].items()):
        o = old_data.get("breakdown", {}).get(name)
        if o is None or pct(comp) > pct(o):
            rises[name] = (pct(o) if o else None, pct(comp))
        else:
            merged["breakdown"][name] = o
            kept.append(name)

    if pct(new_data) > pct(old_data):
        rises["unified"] = (pct(old_data), pct(new_data))
    else:
        for key in ("total_lines", "covered_lines", "coverage_percent"):
            merged[key] = old_data.get(key, merged.get(key))
        kept.append("unified")

    return merged, rises, kept


def render_pr_body() -> str:
    return (
        "## What\n\n"
        "Updates `unified-coverage.json` from the latest successful main CI coverage calculation.\n\n"
        "## Why\n\n"
        "The no-regression gate still uses the committed baseline. This PR keeps branch protection "
        "intact while removing manual baseline file edits after coverage rises.\n"
    )


def open_unified_coverage_baseline_pr(
    *,
    repo_root: Path = REPO_ROOT,
    coverage_context: Path | None = None,
    baseline_branch: str = DEFAULT_BASELINE_BRANCH,
    dry_run: bool = False,
) -> int:
    baseline_path = repo_root / DEFAULT_BASELINE_FILE
    if not baseline_path.exists():
        print(
            f"ERROR: committed baseline file not found: {baseline_path}",
            file=sys.stderr,
        )
        return 1

    old_data = json.loads(baseline_path.read_text(encoding="utf-8"))

    if coverage_context is not None and coverage_context.exists():
        new_data = json.loads(coverage_context.read_text(encoding="utf-8"))
    elif dry_run:
        # In dry-run mode, if no context file is provided, rehearse against the committed baseline
        new_data = old_data
    else:
        print(
            f"ERROR: coverage-context file not found: {coverage_context}",
            file=sys.stderr,
        )
        return 1

    merged, rises, kept = calculate_rise_merge(old_data, new_data)
    print(f"rises: {rises or 'none'}; kept old baseline for: {kept or 'none'}")

    if dry_run:
        print(
            f"[dry-run] Unified coverage baseline PR rehearsal OK "
            f"(target_branch={baseline_branch}, rises={len(rises)}, kept={len(kept)})"
        )
        return 0

    if not rises:
        print("No rounded-percent rise — line-count jitter only; skipping baseline PR.")
        return 0

    # Write merged baseline
    baseline_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    # Run git switch and commit
    subprocess.run(["git", "switch", "-C", baseline_branch], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "github-actions[bot]"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(["git", "add", DEFAULT_BASELINE_FILE], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "chore(ci): update unified coverage baseline"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        ["git", "push", "--force", "origin", f"HEAD:{baseline_branch}"],
        cwd=repo_root,
        check=True,
    )

    github_repo = os.getenv("GITHUB_REPOSITORY", "")
    pr_body = render_pr_body()

    # Check if PR already exists
    view_cmd = ["gh", "pr", "view", baseline_branch]
    if github_repo:
        view_cmd.extend(["--repo", github_repo])
    res = subprocess.run(view_cmd, cwd=repo_root, capture_output=True, text=True)

    if res.returncode == 0:
        edit_cmd = [
            "gh",
            "pr",
            "edit",
            baseline_branch,
            "--title",
            "chore(ci): update unified coverage baseline",
            "--body",
            pr_body,
        ]
        if github_repo:
            edit_cmd.extend(["--repo", github_repo])
        subprocess.run(edit_cmd, cwd=repo_root, check=True)
    else:
        create_cmd = [
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            baseline_branch,
            "--title",
            "chore(ci): update unified coverage baseline",
            "--body",
            pr_body,
        ]
        if github_repo:
            create_cmd.extend(["--repo", github_repo])
        subprocess.run(create_cmd, cwd=repo_root, check=True)

    print("Baseline PR updated successfully.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--coverage-context",
        type=Path,
        default=None,
        help="Path to new unified-coverage.json context.",
    )
    parser.add_argument(
        "--baseline-branch",
        type=str,
        default=os.getenv("BASELINE_BRANCH", DEFAULT_BASELINE_BRANCH),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Rehearse calculation and side-effect parameters without making changes.",
    )
    args = parser.parse_args(argv)
    return open_unified_coverage_baseline_pr(
        repo_root=args.repo_root.resolve(),
        coverage_context=args.coverage_context.resolve()
        if args.coverage_context
        else None,
        baseline_branch=args.baseline_branch,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
