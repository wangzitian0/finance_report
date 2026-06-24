#!/usr/bin/env python3
"""Gate 1c: an AC id must not be defined in BOTH an EPIC table and a package.

During the migration of legacy EPIC-table ACs into package ``roadmap``s, the
common mistake is to add the AC to a package contract but forget to delete its
row from the EPIC table. The registry builder folds the two sources with
``setdefault`` (EPIC wins on collision), so the stale EPIC ``{tier:XX}`` marker
silently overrides the package's tier and nobody is warned.

This gate fails if any AC id appears in both sources, forcing "move ⇒ delete the
EPIC row". It is pure text/AST (no pydantic), so it runs in the CI lint env.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common.ssot.ac_registry_format import sort_key
from common.ssot.generate_ac_registry import (
    EPIC_DIR,
    _epic_files,
    _extract_ac_definition,
    _package_roadmap_acs,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _epic_table_ids(epic_dir: Path) -> set[str]:
    """AC ids defined by an EPIC markdown table/bullet (the legacy source)."""
    ids: set[str] = set()
    for path in _epic_files(epic_dir):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                definition = _extract_ac_definition(line)
                if definition is not None:
                    ids.add(definition[0])
    return ids


def dual_defined_ids(repo_root: Path) -> list[str]:
    """AC ids defined in BOTH an EPIC table and a package roadmap."""
    epic_dir = repo_root / EPIC_DIR
    epic_ids = _epic_table_ids(epic_dir)
    package_ids = set(_package_roadmap_acs(epic_dir).keys())
    return sorted(epic_ids & package_ids, key=sort_key)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail if any AC id is defined in both an EPIC table and a package."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    dual = dual_defined_ids(args.repo_root.resolve())
    if dual:
        for ac_id in dual:
            print(
                f"::error title=AC dual definition::{ac_id} is defined in BOTH an "
                "EPIC table and a package roadmap. When migrating an AC into a "
                "package, DELETE its EPIC-table row (else the stale EPIC tier "
                "silently wins).",
                file=sys.stderr,
            )
        print(
            f"[AC-DUAL] FAILED: {len(dual)} AC id(s) defined in both sources.",
            file=sys.stderr,
        )
        return 1
    print("[AC-DUAL] PASSED: no AC id is defined in both an EPIC table and a package.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
