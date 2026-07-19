"""Fail-closed shrink-only gate for unbound declared package units."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.check_package_contract import discover_packages


def discover_findings(repo_root: Path) -> list[str]:
    if not (repo_root / "common").is_dir():
        raise ValueError(f"missing common package directory {repo_root / 'common'}")
    findings: list[str] = []
    for package in discover_packages(repo_root):
        for unit in package.contract.units:
            if unit.module is None:
                findings.append(f"unbound::{package.name}::{unit.name}")
            if unit.kind.value == "repository" and (
                unit.module is None or unit.impl is None
            ):
                findings.append(f"incomplete-repository::{package.name}::{unit.name}")
    return sorted(findings)


def violations(repo_root: Path, baseline_path: Path) -> list[str]:
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(
            isinstance(item, str) for item in payload
        ):
            raise ValueError("baseline must be a JSON string list")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot read unit-accountability baseline: {exc}"]
    try:
        current = set(discover_findings(repo_root))
    except ValueError as exc:
        return [f"cannot discover unit accountability: {exc}"]
    baseline = set(payload)
    return [
        *(f"new unbound unit: {item}" for item in sorted(current - baseline)),
        *(
            f"stale unit-accountability baseline: {item}"
            for item in sorted(baseline - current)
        ),
    ]


REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def _run_command(argv: Sequence[str] | None = None) -> int:
    repo_root = parse_args(list(argv or ())).repo_root.resolve()
    findings = violations(
        repo_root, repo_root / "common/meta/data/unit-accountability-baseline.json"
    )
    if findings:
        print("[UNIT-ACCOUNTABILITY] FAILED", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("[UNIT-ACCOUNTABILITY] PASSED.")
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
        "UNIT-ACCOUNTABILITY", lambda _root: findings, [], failure_status=status
    )
