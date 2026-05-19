#!/usr/bin/env python3
"""Fail CI when source trees and LCOV reports disagree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coverage_policy import COMPONENTS, ROOT_DIR, CoverageComponent, parse_lcov_sources


def compare_component(component: CoverageComponent, repo_root: Path = ROOT_DIR) -> tuple[list[str], list[str]]:
    expected = component.expected_sources(repo_root)
    reported = parse_lcov_sources(component.lcov_path(repo_root), component, repo_root)
    missing = sorted(expected - reported)
    unexpected = sorted(reported - expected)
    return missing, unexpected


def run_audit(repo_root: Path = ROOT_DIR, components: tuple[CoverageComponent, ...] = COMPONENTS) -> int:
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
            print(f"::error title={component.name} coverage missing files::{len(missing)} source files are absent from LCOV")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Check source tree vs LCOV coverage policy.")
    parser.add_argument("--repo-root", type=Path, default=ROOT_DIR)
    args = parser.parse_args()
    sys.exit(run_audit(args.repo_root.resolve()))


if __name__ == "__main__":
    main()
