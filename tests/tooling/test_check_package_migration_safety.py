"""Tests for the consolidated package migration safety runner."""

from __future__ import annotations

import pytest

from common.meta.base.gate_cli import REPO_ROOT
from common.meta.extension import (
    check_package_migration_safety as safety_gate,
    check_tier_ast_literal,
)


def test_clean_tree_package_migration_safety_passes() -> None:
    """Consolidated package migration safety gate passes on the clean repository."""
    assert safety_gate.violations(REPO_ROOT) == []
    assert safety_gate.main(["--repo-root", str(REPO_ROOT)]) == 0


def test_package_migration_safety_catches_subgate_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Violations from constituent safety gates are aggregated and surfaced."""
    sentinel = "synthetic-error: package tier is not a literal"
    monkeypatch.setattr(
        check_tier_ast_literal,
        "violations",
        lambda repo_root: [sentinel],
    )
    violations = safety_gate.violations(REPO_ROOT)
    assert sentinel in violations
    assert safety_gate.main(["--repo-root", str(REPO_ROOT)]) == 1


def test_package_migration_safety_standard_argparse_status() -> None:
    """Usage error returns standard argparse exit status 2."""
    assert safety_gate.main(["--definitely-invalid"]) == 2
