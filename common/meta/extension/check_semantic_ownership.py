"""Fail-closed gate for duplicate DDD semantic-owner claims."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.base.package_contract import Kind
from common.meta.extension.check_package_contract import (
    DiscoveredPackage,
    discover_packages,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OWNED_KINDS = {
    Kind.AGGREGATE_ROOT,
    Kind.DOMAIN_EVENT,
    Kind.ENTITY,
    Kind.VALUE_OBJECT,
}


def duplicate_claims(packages: Sequence[DiscoveredPackage]) -> list[str]:
    """Project duplicate semantic claims from package-owned unit declarations."""
    owners: dict[tuple[Kind, str], set[str]] = defaultdict(set)
    for package in packages:
        for unit in package.contract.units:
            if unit.kind in OWNED_KINDS:
                owners[unit.kind, unit.semantic_identity].add(package.name)
    return [
        "duplicate semantic owner: "
        f"{kind.value}::{identity}::{','.join(sorted(package_names))}"
        for (kind, identity), package_names in sorted(owners.items(), key=str)
        if len(package_names) > 1
    ]


def violations(repo_root: Path) -> list[str]:
    if not (repo_root / "common").is_dir():
        return [f"cannot discover semantic ownership: missing {repo_root / 'common'}"]
    try:
        return duplicate_claims(discover_packages(repo_root))
    except Exception as exc:
        return [f"cannot discover semantic ownership: {exc}"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def _run_command(argv: Sequence[str] | None = None) -> int:
    findings = violations(parse_args(list(argv or ())).repo_root.resolve())
    if findings:
        print("[SEMANTIC-OWNERSHIP] FAILED", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("[SEMANTIC-OWNERSHIP] PASSED.")
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
        "SEMANTIC-OWNERSHIP", lambda _root: findings, [], failure_status=status
    )


if __name__ == "__main__":
    raise SystemExit(main())
