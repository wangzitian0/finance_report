#!/usr/bin/env python3
"""SSOT ownership lint (closes part of issue #342).

Checks enforced in CI:

  1. **Translation line-count parity**: For each ``DECISIONS_ZH.md`` /
     ``DECISIONS.md`` pair in ``docs/project/``, the ZH file must not
     exceed the EN file in line count (ZH ≤ EN).

  2. **Archived files absent from root**: Certain legacy files must NOT
     exist in ``docs/project/`` root — they must have been moved to
     ``docs/project/archive/``.

  3. **Merged / renamed files absent**: Files that were consolidated
     into another document or renamed must not exist anymore.

  4. **Rule keyword cross-references**: Files outside the designated
     SSOT owner that contain rule-defining keywords must also include
     a ``See: docs/ssot/<file>.md`` cross-reference on the same or an
     adjacent line. Files in ``docs/ssot/`` are always treated as
     canonical owners and are never flagged.

Exit code 0 on success, 1 on any violation.

Run locally::

    python scripts/check_ssot_ownership.py
    python scripts/check_ssot_ownership.py --verbose
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Check 1 — Translation line-count parity
# ---------------------------------------------------------------------------

# Pairs: (zh_path, en_path) — ZH must be ≤ EN in line count.
TRANSLATION_PAIRS: list[tuple[Path, Path]] = [
    (
        REPO_ROOT / "docs" / "project" / "DECISIONS_ZH.md",
        REPO_ROOT / "docs" / "project" / "DECISIONS.md",
    ),
]

# ---------------------------------------------------------------------------
# Check 2 — Archived files must NOT exist in docs/project/ root
# ---------------------------------------------------------------------------

# Files that must have been moved to docs/project/archive/.
MUST_BE_ARCHIVED: list[Path] = [
    REPO_ROOT / "docs" / "project" / "AC-AUDIT-2026-02-25.md",
    REPO_ROOT / "docs" / "project" / "AC-TEST-TRACEABILITY-AUDIT.md",
    REPO_ROOT / "docs" / "project" / "EPIC-ENCODING-SUMMARY.md",
    REPO_ROOT / "docs" / "project" / "TEST-COVERAGE-PLAN.md",
]

# ---------------------------------------------------------------------------
# Check 3 — Merged / renamed files must not exist
# ---------------------------------------------------------------------------

# Files that were merged into another document or renamed; must be absent.
MUST_BE_ABSENT: list[Path] = [
    # EPIC-016 implementation plan merged into EPIC-016.two-stage-review-ui.md
    REPO_ROOT / "docs" / "project" / "EPIC-016-IMPLEMENTATION-PLAN.md",
    # coverage-verification.md merged into docs/ssot/coverage.md
    REPO_ROOT / "docs" / "ssot" / "coverage-verification.md",
    # observability.logging-improvements.md renamed to observability-logging.md
    REPO_ROOT / "docs" / "ssot" / "observability.logging-improvements.md",
]

# ---------------------------------------------------------------------------
# Check 4 — Rule keyword cross-references
# ---------------------------------------------------------------------------

# Each entry: (description, keyword_pattern, canonical_ssot_file, anchor).
# Files outside docs/ssot/ that match keyword_pattern must include a
# cross-reference line containing the canonical_ssot_file string.
# The SSOT file itself is always exempt from this check.
RULE_KEYWORDS: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "Reconciliation score thresholds (≥85 / 60-84 / <60)",
        re.compile(r"(?:≥\s*85|>=\s*85|60[-–]84|<\s*60.*(?:unmatched|review))", re.IGNORECASE),
        "docs/ssot/reconciliation.md",
        "#thresholds",
    ),
    (
        "Decimal monetary rule (never use float)",
        re.compile(r"\bDecimal\b.*\bmonetary\b|\bNEVER\b.*\bfloat\b.*\bamount\b|\bfloat\b.*\bmonetary\b", re.IGNORECASE),
        "docs/ssot/accounting.md",
        "#decimal-rule",
    ),
    (
        "sa.Enum explicit name= rule",
        re.compile(r"sa\.Enum.*name=|Enum.*name=.*explicit", re.IGNORECASE),
        "docs/ssot/schema.md",
        "#enum-naming",
    ),
    (
        "Async transaction boundary (router commits, service flushes)",
        re.compile(r"(?:service-layer.*flush|router.*owns.*commit|db\.flush\(\).*[Ss]ervice|db\.commit\(\).*[Rr]outer|[Ss]ervice.*db\.flush\(\)|[Rr]outer.*db\.commit\(\)|flush\(\).*router.*commit)", re.IGNORECASE),
        "docs/ssot/accounting.md",
        "#async-tx-boundary",
    ),
    (
        "Entry balance invariant (debits = credits)",
        re.compile(r"debits?\s*=\s*credits?|credit.*debit.*balanced|NEVER.*unbalanced", re.IGNORECASE),
        "docs/ssot/accounting.md",
        "#entry-balance",
    ),
]

# Directories and file patterns to skip during keyword scanning.
SCAN_SKIP_DIRS: set[str] = {
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    ".cache",
    ".pytest_cache",
    ".git",
    "archive",  # archived docs are expected to have old copies
}

# Only scan markdown and Python files for rule keyword duplication.
SCAN_SUFFIXES: tuple[str, ...] = (".md", ".py")

# Files that are always exempt from check 4 (canonical owners or root docs
# that are allowed to mention rules without a cross-reference).
CHECK4_EXEMPT_PATHS: set[Path] = {
    REPO_ROOT / "AGENTS.md",  # root policy doc — intentional high-level summaries
    REPO_ROOT / "README.md",  # project overview — summary mention OK
    REPO_ROOT / "vision.md",  # North Star document
}


class Violation(NamedTuple):
    check: str
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def count_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def has_cross_reference(text: str, ssot_file: str) -> bool:
    """Return True if *text* contains a ``See: docs/ssot/<file>`` reference."""
    # Accept either bare filename or full path fragment.
    basename = Path(ssot_file).name
    return ssot_file in text or basename in text


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_translation_parity() -> list[Violation]:
    violations: list[Violation] = []
    for zh_path, en_path in TRANSLATION_PAIRS:
        if not zh_path.exists() or not en_path.exists():
            continue
        zh_lines = count_lines(zh_path)
        en_lines = count_lines(en_path)
        if zh_lines > en_lines:
            violations.append(
                Violation(
                    check="check1_translation_parity",
                    message=(
                        f"{zh_path.relative_to(REPO_ROOT)} has {zh_lines} lines "
                        f"but {en_path.relative_to(REPO_ROOT)} has only {en_lines} lines. "
                        "ZH translation must not exceed EN source."
                    ),
                )
            )
    return violations


def check_must_be_archived() -> list[Violation]:
    violations: list[Violation] = []
    for path in MUST_BE_ARCHIVED:
        if path.exists():
            violations.append(
                Violation(
                    check="check2_must_be_archived",
                    message=(
                        f"{path.relative_to(REPO_ROOT)} must be moved to "
                        f"docs/project/archive/ (found in root)"
                    ),
                )
            )
    return violations


def check_must_be_absent() -> list[Violation]:
    violations: list[Violation] = []
    for path in MUST_BE_ABSENT:
        if path.exists():
            violations.append(
                Violation(
                    check="check3_must_be_absent",
                    message=(
                        f"{path.relative_to(REPO_ROOT)} must not exist — "
                        "it was merged/renamed per SSOT consolidation policy"
                    ),
                )
            )
    return violations


def _collect_scan_files() -> list[Path]:
    """Return all non-archived, non-excluded markdown/Python files."""
    results: list[Path] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        root_path = Path(root)
        # Prune excluded directories in place
        dirs[:] = [
            d for d in dirs
            if d not in SCAN_SKIP_DIRS and not d.startswith(".")
        ]
        for fname in files:
            fpath = root_path / fname
            if fpath.suffix not in SCAN_SUFFIXES:
                continue
            results.append(fpath)
    return results


def check_rule_cross_references() -> list[Violation]:
    violations: list[Violation] = []
    ssot_dir = REPO_ROOT / "docs" / "ssot"

    for fpath in _collect_scan_files():
        # Only check markdown documentation files, not Python source/tests
        if fpath.suffix != ".md":
            continue
        # SSOT files are canonical owners — skip
        if fpath.is_relative_to(ssot_dir):
            continue
        # Exempt root-level policy docs
        if fpath in CHECK4_EXEMPT_PATHS:
            continue

        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for desc, pattern, ssot_file, anchor in RULE_KEYWORDS:
            if not pattern.search(text):
                continue
            # The file mentions the rule keyword; check for cross-reference.
            if has_cross_reference(text, ssot_file):
                continue
            violations.append(
                Violation(
                    check="check4_rule_cross_reference",
                    message=(
                        f"{fpath.relative_to(REPO_ROOT)}: mentions rule "
                        f"'{desc}' but lacks a cross-reference to "
                        f"'{ssot_file}{anchor}'. "
                        f"Add: 'See: {ssot_file}{anchor}'"
                    ),
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SSOT ownership lint (scripts/check_ssot_ownership.py)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print summary even on success.",
    )
    args = parser.parse_args()

    violations: list[Violation] = []
    violations.extend(check_translation_parity())
    violations.extend(check_must_be_archived())
    violations.extend(check_must_be_absent())
    violations.extend(check_rule_cross_references())

    if args.verbose or violations:
        print("=" * 72)
        print("SSOT ownership lint (scripts/check_ssot_ownership.py)")
        print("=" * 72)
        print(f"  Translation pairs checked   : {len(TRANSLATION_PAIRS)}")
        print(f"  Must-be-archived files      : {len(MUST_BE_ARCHIVED)}")
        print(f"  Must-be-absent files        : {len(MUST_BE_ABSENT)}")
        print(f"  Rule keyword checks         : {len(RULE_KEYWORDS)}")
        print()

    if not violations:
        if args.verbose:
            print("OK: SSOT ownership lint passed.")
        return 0

    grouped: dict[str, list[Violation]] = {}
    for v in violations:
        grouped.setdefault(v.check, []).append(v)

    print(
        f"FAIL: SSOT ownership lint found {len(violations)} violation(s) "
        f"across {len(grouped)} check(s).",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for check_name in sorted(grouped):
        items = grouped[check_name]
        print(f"[{check_name}] {len(items)} violation(s):", file=sys.stderr)
        for v in items:
            print(f"  - {v.message}", file=sys.stderr)
        print("", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
