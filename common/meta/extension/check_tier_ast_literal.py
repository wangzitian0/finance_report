#!/usr/bin/env python3
"""Gate 1b: a package's authority tier must be an AST-readable literal.

The AC registry derives every package AC's tier by reading the package
``tier=`` keyword *statically* (AST) from ``common/<pkg>/contract.py`` — it does
NOT import the contract (so it runs in the lightweight CI lint env without
pydantic). The pydantic ``PackageContract`` model, by contrast, resolves the
tier at import time. These two readers agree only while ``tier`` is a plain
string literal: write ``tier=SOME_CONST`` (a module constant or enum) and the AST
reader sees ``None`` (untagging that package's ACs in the registry) while the
model still has a tier — a silent drift, exactly what the package model exists
to kill.

This gate closes that gap WITHOUT importing anything pydantic: every shipped
(non-``draft``) package must expose its tier as a literal in
:data:`common.meta.base.authority_matrix.PACKAGE_TIERS`. (A ``draft`` package may
leave the tier undecided; its ACs are legitimately untagged until it ships.)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.authority_matrix import PACKAGE_TIERS
from common.meta.base.gate_cli import run_gate
from common.meta.extension.generate_ac_registry import package_contract_meta

REPO_ROOT = Path(__file__).resolve().parents[3]


def violations(repo_root: Path) -> list[str]:
    """Return one message per package whose tier is not an AST-readable literal."""
    errors: list[str] = []
    for path in sorted(repo_root.glob("common/*/contract.py")):
        meta = package_contract_meta(path)
        if meta is None:
            continue
        name = meta.get("name") or path.parent.name
        if meta.get("status") == "draft":
            continue
        tier = meta.get("tier")
        if tier not in PACKAGE_TIERS:
            errors.append(
                f"package {name!r} ({path.relative_to(repo_root)}): tier "
                f"{tier!r} is not an AST-readable literal "
                f"(expected one of {list(PACKAGE_TIERS)}). The AC registry reads "
                "tier statically; a non-literal tier silently untags this "
                "package's ACs while the model still carries one. Declare "
                'tier="CODE-ONLY|CODE-LED|LLM-LED|LLM-ONLY" as a plain string literal, or mark the '
                'package status="draft".'
            )
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assert every shipped package's tier is an AST-readable literal."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def _run_command(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    errors = violations(args.repo_root.resolve())
    if errors:
        for message in errors:
            print(f"::error title=AC tier AST literal::{message}", file=sys.stderr)
        print(
            f"[TIER-AST] FAILED: {len(errors)} package(s) whose tier the registry "
            "cannot read statically (AST vs model drift).",
            file=sys.stderr,
        )
        return 1
    print("[TIER-AST] PASSED: every shipped package tier is an AST-readable literal.")
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
        "TIER-AST-LITERAL", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
