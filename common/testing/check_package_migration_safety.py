"""Consolidated runner for package-model migration-safety gates.

Runs the 6 package-model migration safety and contract gates in a single
Python process to eliminate repeated Python runtime startup overhead in CI.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import REPO_ROOT, run_gate
from common.meta.extension import (
    check_authority_reconcile,
    check_draft_packages,
    check_tier_ast_literal,
)
from common.testing import tool_shim_contract


def violations(repo_root: Path) -> list[str]:
    """Aggregate violations from all package migration safety gates."""
    findings: list[str] = []
    findings.extend(check_tier_ast_literal.violations(repo_root))
    findings.extend(check_draft_packages.violations(repo_root, None))
    reconcile_violations, _ = check_authority_reconcile.reconcile(repo_root)
    findings.extend(reconcile_violations)
    tool_baseline = repo_root / tool_shim_contract.DEFAULT_BASELINE.relative_to(
        REPO_ROOT
    )
    new_fat, stale_fat = tool_shim_contract.findings(repo_root, tool_baseline)
    findings.extend(new_fat)
    findings.extend(stale_fat)
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Run consolidated package migration safety gates with standard gate CLI."""
    return run_gate(
        "PACKAGE-MIGRATION-SAFETY",
        violations,
        argv,
        annotation_title="Package Migration Safety",
    )


if __name__ == "__main__":
    raise SystemExit(main())
