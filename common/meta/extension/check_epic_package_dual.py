#!/usr/bin/env python3
"""Gate 1c: an AC id must not be defined in BOTH an EPIC table and a package.

When migrating a legacy EPIC-table AC into a package ``roadmap``, the common
mistake is to add the AC to a package contract but forget to delete its row
from the EPIC table. Since #1719 the registry builder resolves such a
collision roadmap-wins (package contracts are the authoritative source; EPIC
docs feed only explicitly marked residue rows), so a stale EPIC row can no
longer shadow the package's tier — but it would still be a silent duplicate
definition that drifts. This gate keeps collisions impossible in the first
place: it fails if any AC id appears in both sources (marked or not), forcing
"move ⇒ delete the EPIC row". It is pure text/AST (no pydantic), so it runs
in the CI lint env.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.ac_registry_format import sort_key
from common.meta.extension.generate_ac_registry import (
    EPIC_DIR,
    _epic_files,
    _extract_ac_definition,
    _package_roadmap_acs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _run_command(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
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


def main(argv: Sequence[str] | None = None) -> int:
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "EPIC-PACKAGE-DUAL", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
