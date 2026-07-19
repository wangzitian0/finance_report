"""Fail-closed shrink-only gate for package-owned context declarations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.check_package_contract import discover_packages

REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def discover_findings(repo_root: Path) -> list[str]:
    """Return missing contexts and unclassified dependencies from contracts."""
    if not (repo_root / "common").is_dir():
        raise ValueError(f"missing common package directory {repo_root / 'common'}")
    findings: list[str] = []
    for package in discover_packages(repo_root):
        contract = package.contract
        if contract.context is None:
            findings.append(f"missing-context::{contract.name}")
            continue
        classified = {relation.provider for relation in contract.relationships}
        for provider in sorted(set(contract.depends_on) - classified):
            findings.append(f"unclassified-relationship::{contract.name}::{provider}")
    return sorted(findings)


def violations(repo_root: Path, baseline_path: Path) -> list[str]:
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(
            isinstance(item, str) for item in payload
        ):
            raise ValueError("baseline must be a JSON string list")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot read context-contract baseline: {exc}"]
    try:
        current = set(discover_findings(repo_root))
    except ValueError as exc:
        return [f"cannot discover context contracts: {exc}"]
    baseline = {f"missing-context::{item}" for item in payload}
    return [
        *(f"new context-contract debt: {item}" for item in sorted(current - baseline)),
        *(
            f"stale context-contract baseline: {item}"
            for item in sorted(baseline - current)
        ),
    ]


def _run_command(argv: Sequence[str] | None = None) -> int:
    repo_root = parse_args(list(argv or ())).repo_root.resolve()
    findings = violations(
        repo_root, repo_root / "common/meta/data/context-contract-baseline.json"
    )
    if findings:
        print("[CONTEXT-CONTRACT] FAILED", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("[CONTEXT-CONTRACT] PASSED.")
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
        "CONTEXT-CONTRACT", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":
    raise SystemExit(main())
