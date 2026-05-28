#!/usr/bin/env python3
"""Build Coveralls unified LCOV with repository-root-relative source paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common.coverage.policy import COMPONENTS, ROOT_DIR, CoverageComponent


def repo_relative_source(component: CoverageComponent, source_file: str, repo_root: Path = ROOT_DIR) -> str:
    normalized = component.normalize_lcov_source(source_file, repo_root)
    if component.component_root:
        return f"{component.component_root}/{normalized}"
    return normalized


def append_component_lcov(output: Path, component: CoverageComponent, repo_root: Path = ROOT_DIR) -> bool:
    lcov_path = component.lcov_path(repo_root)
    if not lcov_path.exists():
        print(f"Warning: {component.name} LCOV not found: {lcov_path}", file=sys.stderr)
        return False

    with open(lcov_path, "r", encoding="utf-8") as source, open(output, "a", encoding="utf-8") as target:
        for line in source:
            if line.startswith("SF:"):
                target.write(f"SF:{repo_relative_source(component, line[3:].strip(), repo_root)}\n")
            else:
                target.write(line)
    return True


def build_unified_lcov(
    output: Path,
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")

    included = [component.name for component in components if append_component_lcov(output, component, repo_root)]
    if not included:
        print("No LCOV files found for unified report", file=sys.stderr)
        return 1

    print(f"Wrote unified LCOV to {output} from: {', '.join(included)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build repository-root-relative unified LCOV.")
    parser.add_argument("output", nargs="?", type=Path, default=ROOT_DIR / "coverage" / "unified.lcov")
    parser.add_argument("--repo-root", type=Path, default=ROOT_DIR)
    args = parser.parse_args()
    sys.exit(build_unified_lcov(args.output, args.repo_root.resolve()))


if __name__ == "__main__":
    main()
