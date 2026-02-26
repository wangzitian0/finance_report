#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class AC(NamedTuple):
    id: str
    epic: int
    epic_name: str
    description: str
    mandatory: bool


class TraceabilityResult(NamedTuple):
    covered: list[str]
    missing: list[str]
    total: int
    mandatory_total: int


AC_PATTERN = re.compile(r"\bAC(\d+)\.(\d+)\.(\d+)\b")

EXCLUDED_DIRS = {"node_modules", "__pycache__", ".next", "dist", ".cache"}

TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")


def load_registry(registry_path: Path) -> list[AC]:
    if not registry_path.exists():
        print(f"ERROR: AC registry not found: {registry_path}", file=sys.stderr)
        print("  Run: python scripts/generate_ac_registry.py", file=sys.stderr)
        sys.exit(1)

    with open(registry_path) as f:
        data = yaml.safe_load(f)

    return [
        AC(
            id=entry["id"],
            epic=entry["epic"],
            epic_name=entry.get("epic_name", ""),
            description=entry.get("description", ""),
            mandatory=entry.get("mandatory", True),
        )
        for entry in data.get("acs", [])
    ]


def find_test_files(test_dirs: list[Path]) -> list[Path]:
    test_files: list[Path] = []
    for base in test_dirs:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for fname in files:
                if fname.startswith("test_") or fname.endswith(TEST_FILE_SUFFIXES):
                    test_files.append(Path(root) / fname)
    return test_files


def collect_referenced_acs(test_files: list[Path]) -> dict[str, list[str]]:
    references: dict[str, list[str]] = {}
    for fpath in test_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in AC_PATTERN.finditer(content):
            ac_id = m.group(0)
            references.setdefault(ac_id, []).append(str(fpath))
    return references


def check_traceability(
    acs: list[AC], references: dict[str, list[str]]
) -> TraceabilityResult:
    mandatory = [ac for ac in acs if ac.mandatory]
    covered = [ac.id for ac in mandatory if ac.id in references]
    missing = [ac.id for ac in mandatory if ac.id not in references]
    return TraceabilityResult(
        covered=covered, missing=missing, total=len(acs), mandatory_total=len(mandatory)
    )


def print_report(
    result: TraceabilityResult,
    acs: list[AC],
    references: dict[str, list[str]],
    verbose: bool = False,
) -> None:
    ac_by_id = {ac.id: ac for ac in acs}
    coverage_pct = (
        len(result.covered) / result.mandatory_total * 100
        if result.mandatory_total > 0
        else 0
    )

    print(f"\n{'=' * 60}")
    print("AC TRACEABILITY REPORT")
    print(f"{'=' * 60}")
    print(f"Registry: {result.total} total ACs, {result.mandatory_total} mandatory")
    print(f"Covered : {len(result.covered)} ({coverage_pct:.1f}%)")
    print(f"Missing : {len(result.missing)}")
    print(f"{'=' * 60}\n")

    if result.missing:
        print("WARNING: ACs WITH NO TEST REFERENCE (gaps):\n")
        by_epic: dict[int, list[str]] = {}
        for ac_id in sorted(
            result.missing, key=lambda x: [int(p) for p in x[2:].split(".")]
        ):
            by_epic.setdefault(ac_by_id[ac_id].epic, []).append(ac_id)
        for epic_num in sorted(by_epic):
            ac_sample = ac_by_id[by_epic[epic_num][0]]
            print(f"  EPIC-{epic_num:03d} ({ac_sample.epic_name}):")
            for ac_id in by_epic[epic_num]:
                print(f"    MISSING {ac_id}: {ac_by_id[ac_id].description}")
        print()

    if verbose and result.covered:
        print("ACs WITH TEST COVERAGE:\n")
        for ac_id in sorted(
            result.covered, key=lambda x: [int(p) for p in x[2:].split(".")]
        ):
            print(f"  OK {ac_id}: {ac_by_id[ac_id].description}")
            for f in references.get(ac_id, [])[:2]:
                print(f"       -> {f}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that every mandatory AC has at least one test reference."
    )
    parser.add_argument("--registry", default="docs/ac_registry.yaml")
    parser.add_argument(
        "--test-dirs", nargs="+", default=["apps/backend/tests", "apps/frontend/src"]
    )
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry_path = Path(args.registry)
    test_dirs = [Path(d) for d in args.test_dirs]

    acs = load_registry(registry_path)
    print(f"Loaded {len(acs)} ACs from {registry_path}")

    test_files = find_test_files(test_dirs)
    print(f"Scanning {len(test_files)} test files in: {[str(d) for d in test_dirs]}")

    references = collect_referenced_acs(test_files)
    print(f"Found AC references to {len(references)} unique ACs in tests")

    result = check_traceability(acs, references)
    print_report(result, acs, references, verbose=args.verbose)

    if result.missing and not args.report_only:
        print(
            f"TRACEABILITY GATE FAILED: {len(result.missing)} mandatory AC(s) have no test reference.\n"
            f'  Add docstrings like """AC{result.missing[0]}: description""" to at least one test per AC.',
            file=sys.stderr,
        )
        return 1

    if not result.missing:
        print(
            f"TRACEABILITY GATE PASSED: all {result.mandatory_total} mandatory ACs have test coverage."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
