"""Unit-accountability ratchet for #1894."""

from __future__ import annotations

import json
from pathlib import Path

from common.meta.extension.check_unit_accountability import main, violations


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_AC_meta_dependency_governance_6_unit_accountability_is_exact(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.6: missing unit bindings fail closed."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps([]), encoding="utf-8")

    findings = violations(tmp_path, baseline)

    assert any("cannot discover unit accountability" in finding for finding in findings)


def test_unit_accountability_baseline_is_exact_on_real_repository() -> None:
    assert (
        violations(
            REPO_ROOT, REPO_ROOT / "common/meta/data/unit-accountability-baseline.json"
        )
        == []
    )
    assert main() == 0
