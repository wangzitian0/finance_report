#!/usr/bin/env python3
"""Diff-scoped PR coverage gate (#1810, G-diff-coverage).

On pull requests the BLOCKING coverage verdict is computed from the PR's own
diff plus per-component LCOV: every changed/added line that falls inside a
governed source tree (``common/meta/extension/coverage/policy.py``) must be
covered by tests at or above the threshold (default 85%). A red verdict names
the uncovered lines as ``file: uncovered lines a-b, c`` ranges, so the fix is
never a guess. The component-percentage ratchet
(``calculate_unified_coverage.py``) stays the blocking water-line on main
pushes only.

Scope rules:

- Changed files that resolve to no coverage component (docs, tests, configs,
  workflows, policy-excluded files) are out of scope — ignored.
- A changed line absent from a PRESENT file record is non-executable
  (blank/comment) — skipped.
- A changed in-scope file entirely absent from its component's loaded LCOV is
  counted conservatively: its added non-blank, non-comment lines are
  uncovered. This is exactly the "new file with zero tests" hole.
- A component whose LCOV artifact is entirely absent is skipped with a loud
  warning — lenient parity with the CI merge step, which tolerates
  legitimately-absent artifacts.

Local parity: run your test suite with ``--cov`` (producing an LCOV for the
touched component), then ``python tools/check_diff_coverage.py --base
origin/main``.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from common.meta.extension.coverage.policy import (
    COMPONENTS,
    CoverageComponent,
    get_component,
)

ROOT_DIR = Path(__file__).resolve().parents[3]

DEFAULT_THRESHOLD = 85.0
DEFAULT_BASE = "origin/main"

#: Env fallbacks for the CLI flags (flag wins when both are given).
THRESHOLD_ENV = "DIFF_COVERAGE_THRESHOLD"
BASE_ENV = "DIFF_COVERAGE_BASE"

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

#: Line prefixes treated as non-executable for the conservative
#: missing-from-LCOV rule (Python and TS/TSX comment markers).
_COMMENT_PREFIXES = ("#", "//")


def parse_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """Map ``git diff -U0`` output to {repo-relative path: added line numbers}.

    Tracks ``+++ b/<path>`` targets and ``@@ -a[,b] +c[,d] @@`` hunk headers:
    the new-side lines are ``c..c+d-1`` (``d`` defaults to 1; ``d=0`` is a pure
    deletion and contributes no lines). Deleted files (``+++ /dev/null``) and
    pure renames (no hunks) contribute nothing.
    """
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target.startswith('"') and target.endswith('"'):
                target = target[1:-1]
            if target == "/dev/null":
                current = None
            elif target.startswith("b/"):
                current = target[2:]
            else:
                current = target
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
    """Resolve a changed repo-relative path to (component, LCOV source path).

    A path is in scope iff it lives under a component's governed source root,
    carries one of the component's extensions, and is not policy-excluded.
    Returns ``None`` for out-of-scope paths (docs, tests, configs, workflows).
    """
    path = repo_relative_path.replace("\\", "/")
    for component in components:
        prefix_parts = [
            part for part in (component.component_root, component.source_subdir) if part
        ]
        source_prefix = "/".join(prefix_parts) + "/"
        if not path.startswith(source_prefix):
            continue
        if not path.endswith(component.extensions):
            continue
        if component.component_root:
            component_relative = path[len(component.component_root) + 1 :]
        else:
            component_relative = path
        if component.is_excluded(component_relative):
            continue
        return component, component_relative
    return None


def parse_lcov_line_hits(
    lcov_path: Path,
    component: CoverageComponent,
    repo_root: Path = ROOT_DIR,
) -> dict[str, dict[int, int]]:
    """Parse LCOV ``DA:<line>,<hits>`` records per normalized source path.

    Sources are normalized via ``component.normalize_lcov_source`` and hits
    are summed across duplicate ``SF:`` records for the same source (merged
    shards), mirroring the flush/accumulate semantics of
    ``calculate_unified_coverage.parse_lcov_records``.
    """
    if not lcov_path.exists():
        return {}

    hits: dict[str, dict[int, int]] = {}
    current_source = ""
    with open(lcov_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if line.startswith("SF:"):
                current_source = component.normalize_lcov_source(line[3:], repo_root)
                hits.setdefault(current_source, {})
            elif line.startswith("DA:") and current_source:
                fields = line[3:].split(",")
                try:
                    line_no = int(fields[0])
                    hit_count = int(fields[1])
                except (IndexError, ValueError):
                    continue
                file_hits = hits[current_source]
                file_hits[line_no] = file_hits.get(line_no, 0) + hit_count
            elif line == "end_of_record":
                current_source = ""
    return hits


def _significant_lines(file_path: Path, line_numbers: set[int]) -> tuple[int, ...]:
    """Filter added line numbers down to non-blank, non-comment lines.

    Used by the conservative missing-from-LCOV rule. When the file cannot be
    read, every added line counts (stay conservative).
    """
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return tuple(sorted(line_numbers))
    significant: list[int] = []
    for line_no in sorted(line_numbers):
        if not 1 <= line_no <= len(lines):
            continue
        stripped = lines[line_no - 1].strip()
        if not stripped or stripped.startswith(_COMMENT_PREFIXES):
            continue
        significant.append(line_no)
    return tuple(significant)


@dataclass(frozen=True)
class FileVerdict:
    """Per-file diff-coverage verdict (line numbers are repo-file 1-based)."""

    path: str
    component: str
    covered_lines: tuple[int, ...]
    uncovered_lines: tuple[int, ...]
    #: True when the file has no record in its component's (present) LCOV —
    #: the conservative "new file with zero tests" case.
    missing_from_lcov: bool = False


@dataclass(frozen=True)
class DiffCoverageReport:
    """Aggregated diff-coverage verdict over every in-scope changed file."""

    files: tuple[FileVerdict, ...]
    #: Components with in-scope changed files but an entirely absent LCOV
    #: artifact — skipped leniently (CI merge-step parity), warned loudly.
    skipped_components: tuple[str, ...]

    @property
    def measurable_lines(self) -> int:
        return sum(
            len(verdict.covered_lines) + len(verdict.uncovered_lines)
            for verdict in self.files
        )

    @property
    def covered_count(self) -> int:
        return sum(len(verdict.covered_lines) for verdict in self.files)

    @property
    def percent(self) -> float | None:
        measurable = self.measurable_lines
        if measurable == 0:
            return None
        return self.covered_count / measurable * 100


def evaluate_diff_coverage(
    changed_lines: dict[str, set[int]],
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> DiffCoverageReport:
    """Compute the diff-coverage verdict for parsed changed lines."""
    lcov_cache: dict[str, dict[str, dict[int, int]] | None] = {}
    verdicts: list[FileVerdict] = []
    skipped_components: list[str] = []

    for path in sorted(changed_lines):
        lines = changed_lines[path]
        if not lines:
            continue
        resolved = resolve_component(path, components)
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
            if component.name not in skipped_components:
                skipped_components.append(component.name)
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

        covered: list[int] = []
        uncovered: list[int] = []
        for line_no in sorted(lines):
            if line_no not in file_hits:
                continue  # non-executable (blank/comment): not in the record
            if file_hits[line_no] > 0:
                covered.append(line_no)
            else:
                uncovered.append(line_no)
        verdicts.append(
            FileVerdict(
                path=path,
                component=component.name,
                covered_lines=tuple(covered),
                uncovered_lines=tuple(uncovered),
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
            continue
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
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff against {base!r} failed: {result.stderr.strip()}")
    return result.stdout


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diff-scoped PR coverage gate (#1810): changed/added lines in "
            "governed source trees must be covered by tests at or above the "
            "threshold."
        )
    )
    parser.add_argument(
        "--base",
        default=None,
        help=(
            "Base ref for the merge-base diff (default: the "
            f"{BASE_ENV} env var, else {DEFAULT_BASE!r}). Ignored when "
            "--diff-file is given."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Minimum percent of measurable changed lines that must be covered "
            f"(default: the {THRESHOLD_ENV} env var, else {DEFAULT_THRESHOLD:g})."
        ),
    )
    parser.add_argument(
        "--diff-file",
        default=None,
        metavar="PATH",
        help=(
            "Read unified diff text from PATH instead of running git "
            "(deterministic input for tests and offline runs)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        metavar="PATH",
        help=(
            "Repository root to resolve LCOV artifacts and changed files "
            "against (default: this checkout)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: exit 0 on pass (or nothing to gate), 1 below threshold,
    2 on usage/environment errors."""
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
                    f"❌ Invalid {THRESHOLD_ENV}: {raw_threshold!r} "
                    "(expected a number)",
                    file=sys.stderr,
                )
                return 2
        else:
            threshold = DEFAULT_THRESHOLD

    print("=" * 60)
    print("Diff Coverage Gate (#1810)")
    print("=" * 60)

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
        if verdict.missing_from_lcov:
            print(
                f"❌ {verdict.path}: uncovered lines {ranges} "
                f"(file not in {verdict.component} LCOV — a new file with zero "
                "tests? all added code lines counted uncovered)"
            )
        else:
            print(f"❌ {verdict.path}: uncovered lines {ranges}")

    percent = report.percent
    assert percent is not None  # measurable_lines > 0 here
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
