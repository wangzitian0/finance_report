#!/usr/bin/env python3
"""SSOT Manifest consistency checker (closes meta-issue horizontal-axis).

Validates ``docs/ssot/MANIFEST.yaml`` against the following rules:

  1. No two concepts may share the same owner (file + optional anchor).
  2. Every owner *file* path (ignoring ``#anchor``) MUST exist on disk.
  3. Every cross_ref *file* path (ignoring ``#anchor``) MUST exist on disk.

The script exits 0 on success and 1 on any violation.

Usage::

    python scripts/check_manifest.py
    python scripts/check_manifest.py --verbose

Run in CI alongside ``scripts/lint_doc_consistency.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "ssot" / "MANIFEST.yaml"


class Violation(NamedTuple):
    check: str
    message: str


def _file_part(ref: str) -> str:
    """Strip optional ``#anchor`` from a path string and return the file part."""
    return ref.split("#")[0]


def load_manifest(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: MANIFEST.yaml not found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def check_concept_schema(concepts: dict) -> list[Violation]:
    """Rule 0: every concept value must be a mapping (dict), not null or scalar."""
    violations: list[Violation] = []
    for concept_key, concept_data in concepts.items():
        if not isinstance(concept_data, dict):
            violations.append(
                Violation(
                    check="check0_concept_schema",
                    message=(
                        f"Concept '{concept_key}' must be a YAML mapping but got "
                        f"{type(concept_data).__name__!r}. "
                        "Expected keys: owner, description, cross_refs."
                    ),
                )
            )
    return violations


def check_duplicate_owners(concepts: dict) -> list[Violation]:
    """Rule 1: no two concepts may share the same owner."""
    owner_to_concepts: dict[str, list[str]] = {}
    for concept_key, concept_data in concepts.items():
        if not isinstance(concept_data, dict):
            continue
        owner = concept_data.get("owner", "")
        if not owner:
            continue
        owner_to_concepts.setdefault(owner, []).append(concept_key)

    violations: list[Violation] = []
    for owner, keys in owner_to_concepts.items():
        if len(keys) > 1:
            joined = ", ".join(sorted(keys))
            violations.append(
                Violation(
                    check="check1_duplicate_owners",
                    message=(
                        f"Owner '{owner}' is claimed by multiple concepts: {joined}"
                    ),
                )
            )
    return violations


def check_owner_files_exist(concepts: dict) -> list[Violation]:
    """Rule 2: every owner file path must exist on disk."""
    violations: list[Violation] = []
    for concept_key, concept_data in concepts.items():
        if not isinstance(concept_data, dict):
            continue
        owner = concept_data.get("owner", "")
        if not owner:
            violations.append(
                Violation(
                    check="check2_owner_exists",
                    message=f"Concept '{concept_key}' has no 'owner' field.",
                )
            )
            continue
        file_path = REPO_ROOT / _file_part(owner)
        if not file_path.exists():
            violations.append(
                Violation(
                    check="check2_owner_exists",
                    message=(
                        f"Concept '{concept_key}': owner file does not exist: "
                        f"'{_file_part(owner)}'"
                    ),
                )
            )
    return violations


def check_crossref_files_exist(concepts: dict) -> list[Violation]:
    """Rule 3: every cross_ref file path must exist on disk."""
    violations: list[Violation] = []
    for concept_key, concept_data in concepts.items():
        if not isinstance(concept_data, dict):
            continue
        cross_refs = concept_data.get("cross_refs")
        if cross_refs is None:
            continue
        if not isinstance(cross_refs, list):
            violations.append(
                Violation(
                    check="check3_crossref_exists",
                    message=(
                        f"Concept '{concept_key}': 'cross_refs' must be a YAML list "
                        f"but got {type(cross_refs).__name__!r}."
                    ),
                )
            )
            continue
        for ref in cross_refs:
            if not isinstance(ref, str):
                violations.append(
                    Violation(
                        check="check3_crossref_exists",
                        message=(
                            f"Concept '{concept_key}': cross_ref entry must be a "
                            f"string but got {type(ref).__name__!r}: {ref!r}"
                        ),
                    )
                )
                continue
            file_path = REPO_ROOT / _file_part(ref)
            if not file_path.exists():
                violations.append(
                    Violation(
                        check="check3_crossref_exists",
                        message=(
                            f"Concept '{concept_key}': cross_ref file does not "
                            f"exist: '{_file_part(ref)}'"
                        ),
                    )
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate docs/ssot/MANIFEST.yaml consistency."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print summary statistics even on success.",
    )
    args = parser.parse_args()

    data = load_manifest(MANIFEST_PATH)
    concepts: dict = data.get("concepts", {})

    if not concepts:
        print("ERROR: No concepts found in MANIFEST.yaml.", file=sys.stderr)
        return 1

    violations: list[Violation] = []
    violations.extend(check_concept_schema(concepts))
    violations.extend(check_duplicate_owners(concepts))
    violations.extend(check_owner_files_exist(concepts))
    violations.extend(check_crossref_files_exist(concepts))

    if args.verbose or violations:
        print("=" * 72)
        print("SSOT Manifest check (scripts/check_manifest.py)")
        print("=" * 72)
        print(f"  Concepts in manifest : {len(concepts)}")
        print()

    if not violations:
        if args.verbose:
            print("OK: manifest check passed.")
        return 0

    grouped: dict[str, list[Violation]] = {}
    for violation in violations:
        grouped.setdefault(violation.check, []).append(violation)

    print(
        f"FAIL: manifest check found {len(violations)} violation(s) "
        f"across {len(grouped)} check(s).",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for check_name in sorted(grouped):
        items = grouped[check_name]
        print(f"[{check_name}] {len(items)} violation(s):", file=sys.stderr)
        for violation in items:
            print(f"  - {violation.message}", file=sys.stderr)
        print("", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
