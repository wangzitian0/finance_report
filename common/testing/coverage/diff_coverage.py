#!/usr/bin/env python3
"""Diff-scoped PR coverage gate (#1810, G-diff-coverage)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from common.meta.extension.coverage.policy import (
    COMPONENTS,
    CoverageComponent,
    get_component,
)
from common.testing.coverage.lcov import parse_line_hits

ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_THRESHOLD = 85.0
DEFAULT_BASE = "origin/main"
THRESHOLD_ENV = "DIFF_COVERAGE_THRESHOLD"
BASE_ENV = "DIFF_COVERAGE_BASE"

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_COMMENT_PREFIXES = ("#", "//")


def parse_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """Map ``git diff -U0`` output to {repo-relative path: added line numbers}."""
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip().strip('"')
            current = (
                None
                if target == "/dev/null"
                else (target[2:] if target.startswith("b/") else target)
            )
            continue
        match = _HUNK_RE.match(line)
        if match and current is not None:
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            if count > 0:
                changed.setdefault(current, set()).update(range(start, start + count))
    return changed


def resolve_component(
    repo_relative_path: str,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> tuple[CoverageComponent, str] | None:
    """Resolve a changed repo-relative path to (component, LCOV source path)."""
    path = repo_relative_path.replace("\\", "/")
    for component in components:
        prefix_parts = [
            p for p in (component.component_root, component.source_subdir) if p
        ]
        if not path.startswith("/".join(prefix_parts) + "/") or not path.endswith(
            component.extensions
        ):
            continue
        component_relative = (
            path[len(component.component_root) + 1 :]
            if component.component_root
            else path
        )
        if not component.is_excluded(component_relative):
            return component, component_relative
    return None


def parse_lcov_line_hits(
    lcov_path: Path,
    component: CoverageComponent,
    repo_root: Path = ROOT_DIR,
) -> dict[str, dict[int, int]]:
    """Parse LCOV ``DA:<line>,<hits>`` records per normalized source path."""
    return parse_line_hits(
        lcov_path,
        normalize_source=lambda src: component.normalize_lcov_source(src, repo_root),
        accumulate="sum",
    )


def _significant_lines(file_path: Path, line_numbers: set[int]) -> tuple[int, ...]:
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return tuple(sorted(line_numbers))
    return tuple(
        line_no
        for line_no in sorted(line_numbers)
        if 1 <= line_no <= len(lines)
        and (stripped := lines[line_no - 1].strip())
        and not stripped.startswith(_COMMENT_PREFIXES)
    )


@dataclass(frozen=True)
class FileVerdict:
    path: str
    component: str
    covered_lines: tuple[int, ...]
    uncovered_lines: tuple[int, ...]
    missing_from_lcov: bool = False


@dataclass(frozen=True)
class DiffCoverageReport:
    files: tuple[FileVerdict, ...]
    skipped_components: tuple[str, ...]

    @property
    def measurable_lines(self) -> int:
        return sum(len(v.covered_lines) + len(v.uncovered_lines) for v in self.files)

    @property
    def covered_count(self) -> int:
        return sum(len(v.covered_lines) for v in self.files)

    @property
    def percent(self) -> float | None:
        measurable = self.measurable_lines
        return None if measurable == 0 else self.covered_count / measurable * 100


def evaluate_diff_coverage(
    changed_lines: dict[str, set[int]],
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> DiffCoverageReport:
    """Compute the diff-coverage verdict for parsed changed lines."""
    lcov_cache: dict[str, dict[str, dict[int, int]] | None] = {}
    verdicts: list[FileVerdict] = []
    skipped_components: set[str] = set()

    for path in sorted(changed_lines):
        lines = changed_lines[path]
        resolved = resolve_component(path, components) if lines else None
        if resolved is None:
            continue
        component, component_relative = resolved
        if component.name not in lcov_cache:
            lcov_path = component.lcov_path(repo_root)
            lcov_cache[component.name] = (
                parse_lcov_line_hits(lcov_path, component, repo_root)
                if lcov_path.exists()
                else None
            )
        component_hits = lcov_cache[component.name]
        if component_hits is None:
            skipped_components.add(component.name)
            continue

        file_hits = component_hits.get(component_relative)
        if file_hits is None:
            verdicts.append(
                FileVerdict(
                    path=path,
                    component=component.name,
                    covered_lines=(),
                    uncovered_lines=_significant_lines(repo_root / path, lines),
                    missing_from_lcov=True,
                )
            )
            continue

        covered = tuple(
            ln for ln in sorted(lines) if ln in file_hits and file_hits[ln] > 0
        )
        uncovered = tuple(
            ln for ln in sorted(lines) if ln in file_hits and file_hits[ln] <= 0
        )
        verdicts.append(
            FileVerdict(
                path=path,
                component=component.name,
                covered_lines=covered,
                uncovered_lines=uncovered,
            )
        )

    return DiffCoverageReport(
        files=tuple(verdicts),
        skipped_components=tuple(sorted(skipped_components)),
    )


def format_line_ranges(lines: Iterable[int]) -> str:
    """Render line numbers as compact ranges: [45,46,47,48,92] -> '45-48, 92'."""
    ordered = sorted(set(lines))
    if not ordered:
        return ""
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for line_no in ordered[1:]:
        if line_no == previous + 1:
            previous = line_no
        else:
            ranges.append((start, previous))
            start = previous = line_no
    ranges.append((start, previous))
    return ", ".join(
        str(first) if first == last else f"{first}-{last}" for first, last in ranges
    )


def git_diff_text(base: str, repo_root: Path = ROOT_DIR) -> str:
    """Return ``git diff -U0`` text from the merge-base of ``base`` to HEAD."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "-U0",
            "--diff-filter=ACMR",
            "--merge-base",
            base,
            "HEAD",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff against {base!r} failed: {result.stderr.strip()}")
    return result.stdout


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diff-scoped PR coverage gate (#1810)."
    )
    parser.add_argument("--base", default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--diff-file", default=None, metavar="PATH")
    parser.add_argument("--repo-root", default=None, metavar="PATH")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT_DIR

    threshold = args.threshold
    if threshold is None:
        raw_threshold = os.environ.get(THRESHOLD_ENV, "").strip()
        if raw_threshold:
            try:
                threshold = float(raw_threshold)
            except ValueError:
                print(
                    f"❌ Invalid {THRESHOLD_ENV}: {raw_threshold!r} (expected a number)",
                    file=sys.stderr,
                )
                return 2
        else:
            threshold = DEFAULT_THRESHOLD

    print(f"{'=' * 60}\nDiff Coverage Gate (#1810)\n{'=' * 60}")
    if args.diff_file:
        diff_path = Path(args.diff_file)
        if not diff_path.exists():
            print(f"❌ Diff file not found: {diff_path}", file=sys.stderr)
            return 2
        diff_text = diff_path.read_text(encoding="utf-8", errors="ignore")
        print(f"   diff source: {diff_path}")
    else:
        base = args.base or os.environ.get(BASE_ENV, "").strip() or DEFAULT_BASE
        try:
            diff_text = git_diff_text(base, repo_root)
        except RuntimeError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        print(f"   diff source: git diff --merge-base {base} HEAD")

    report = evaluate_diff_coverage(parse_unified_diff(diff_text), repo_root)
    for name in report.skipped_components:
        component = get_component(name)
        print(
            f"⚠️  WARNING: {name}: coverage artifact absent (expected "
            f"{component.ci_lcov_path}); skipping its changed files — lenient "
            "parity with the CI merge step, which tolerates absent artifacts"
        )

    if report.measurable_lines == 0:
        print(
            "✅ diff coverage: no measurable changed lines "
            "(out-of-scope or non-executable diff) — nothing to gate"
        )
        return 0

    for verdict in report.files:
        if not verdict.uncovered_lines:
            continue
        ranges = format_line_ranges(verdict.uncovered_lines)
        suffix = (
            f" (file not in {verdict.component} LCOV — a new file with zero tests? all added code lines counted uncovered)"
            if verdict.missing_from_lcov
            else ""
        )
        print(f"❌ {verdict.path}: uncovered lines {ranges}{suffix}")

    percent = report.percent
    assert percent is not None
    summary = (
        f"diff coverage: {percent:.1f}% ({report.covered_count}/"
        f"{report.measurable_lines} measurable changed lines covered), "
        f"threshold {threshold:g}%"
    )
    if percent >= threshold:
        print(f"✅ {summary}")
        return 0

    print(f"❌ {summary}")
    print(
        "   Cover the uncovered changed lines listed above with tests, then "
        "re-check locally: run your suite with --cov to produce the component "
        "LCOV and re-run tools/check_diff_coverage.py.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
