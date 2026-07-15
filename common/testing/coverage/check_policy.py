#!/usr/bin/env python3
"""Fail CI when source trees and LCOV reports disagree."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

from common.meta.extension.coverage.policy import (
    COMPONENTS,
    ROOT_DIR,
    CoverageComponent,
    find_unregistered_sources,
    parse_lcov_sources,
)


def compare_component(
    component: CoverageComponent, repo_root: Path = ROOT_DIR
) -> tuple[list[str], list[str]]:
    expected = component.expected_sources(repo_root)
    reported = parse_lcov_sources(component.lcov_path(repo_root), component, repo_root)
    missing = sorted(expected - reported)
    unexpected = sorted(reported - expected)
    return missing, unexpected


def run_audit(
    repo_root: Path = ROOT_DIR, components: tuple[CoverageComponent, ...] = COMPONENTS
) -> int:
    failed = False

    for component in components:
        lcov_path = component.lcov_path(repo_root)
        missing, unexpected = compare_component(component, repo_root)
        expected_count = len(component.expected_sources(repo_root))
        reported_count = len(parse_lcov_sources(lcov_path, component, repo_root))

        print(
            f"{component.name}: expected={expected_count} reported={reported_count} "
            f"lcov={lcov_path.relative_to(repo_root) if lcov_path.exists() else lcov_path}"
        )

        if missing:
            failed = True
            print(
                f"::error title={component.name} coverage missing files::{len(missing)} source files are absent from LCOV"
            )
            for path in missing[:50]:
                print(f"  missing: {path}")
            if len(missing) > 50:
                print(f"  ... {len(missing) - 50} more missing files")

        if unexpected:
            failed = True
            print(
                f"::error title={component.name} coverage unexpected files::"
                f"{len(unexpected)} LCOV files are outside the coverage policy"
            )
            for path in unexpected[:50]:
                print(f"  unexpected: {path}")
            if len(unexpected) > 50:
                print(f"  ... {len(unexpected) - 50} more unexpected files")

    if failed:
        return 1

    print("Coverage policy audit passed.")
    return 0


def tracked_source_files(repo_root: Path = ROOT_DIR) -> list[str]:
    """Repo-relative tracked Python/TypeScript source paths (git is the truth)."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "*.py", "*.ts", "*.tsx"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def audit_unregistered_sources(repo_root: Path = ROOT_DIR) -> int:
    """Fail when a tracked source tree is neither covered nor explicitly exempt."""
    orphans = find_unregistered_sources(tracked_source_files(repo_root), repo_root)
    if orphans:
        print(
            f"::error title=Unregistered source tree::{len(orphans)} tracked source "
            "file(s) live outside every coverage component and are not exempt; "
            "move them under a covered root or register them in "
            "common/meta/extension/coverage/policy.py::COVERAGE_EXEMPT_PATTERNS"
        )
        for path in orphans[:50]:
            print(f"  unregistered: {path}")
        if len(orphans) > 50:
            print(f"  ... {len(orphans) - 50} more unregistered files")
        return 1
    print(
        "Coverage registration audit passed: all tracked source is covered or exempt."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check source tree vs LCOV coverage policy."
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT_DIR)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    result = run_audit(repo_root)
    if result == 0:
        result = audit_unregistered_sources(repo_root)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
