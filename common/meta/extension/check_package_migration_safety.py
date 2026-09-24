"""Consolidated runner for package-model migration-safety gates.

Runs the 7 package-model migration safety and contract gates in a single
Python process to eliminate repeated Python runtime startup overhead in CI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import REPO_ROOT, run_gate
from common.meta.extension import (
    check_authority_reconcile,
    check_draft_packages,
    check_epic_package_dual,
    check_tier_ast_literal,
)
from common.testing import (
    baseline_update_contract,
    gate_main_contract,
    tool_shim_contract,
)


def violations(repo_root: Path) -> list[str]:
    """Aggregate violations from all 7 package migration safety gates."""
    findings: list[str] = []
    findings.extend(check_tier_ast_literal.violations(repo_root))
    dual = check_epic_package_dual.dual_defined_ids(repo_root)
    findings.extend(
        [
            f"{ac_id} is defined in both an EPIC table and a package roadmap"
            for ac_id in dual
        ]
    )
    draft_baseline = repo_root / check_draft_packages.DEFAULT_BASELINE.relative_to(
        REPO_ROOT
    )
    findings.extend(check_draft_packages.violations(repo_root, draft_baseline))
    reconcile_violations, _ = check_authority_reconcile.reconcile(repo_root)
    findings.extend(reconcile_violations)
    findings.extend(gate_main_contract.violations(repo_root))
    findings.extend(baseline_update_contract.violations(repo_root))
    tool_baseline = repo_root / tool_shim_contract.DEFAULT_BASELINE.relative_to(
        REPO_ROOT
    )
    new_fat, stale_fat = tool_shim_contract.findings(repo_root, tool_baseline)
    findings.extend(new_fat)
    findings.extend(stale_fat)
    return findings


def _run_command(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run consolidated package migration safety gates."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    findings = violations(args.repo_root.resolve())
    if findings:
        for finding in findings:
            print(f"::error title=Package Migration Safety::{finding}", file=sys.stderr)
        return 1
    print("[PACKAGE-MIGRATION-SAFETY] PASSED: all 7 migration safety gates satisfied.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run consolidated package migration safety gates with standard gate CLI."""
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "PACKAGE-MIGRATION-SAFETY",
        lambda _repo_root: findings,
        [],
        failure_status=status,
    )


if __name__ == "__main__":
    raise SystemExit(main())
