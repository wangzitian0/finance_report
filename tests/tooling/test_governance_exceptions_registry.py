"""Contracts for the bottom-up proof-exception and code-owned-surface registry.

Issue #524: classify proof exceptions and code-owned surfaces into a registry
the existing governance gates can read. The registry lives in
``common/meta/data/governance-exceptions.yaml`` and is validated by
``tools/check_governance_exceptions.py``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from common.meta.extension import check_governance_exceptions as gec

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "common" / "meta" / "data" / "governance-exceptions.yaml"


def test_AC8_13_131_registry_separates_proof_exceptions_and_code_owned_surfaces() -> (
    None
):
    """AC8.13.131: registry carries typed proof-exception and code-owned-surface lists."""
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # The legacy SSOT governance gate exception list stays intact.
    assert "exceptions" in data
    # New bottom-up classification surfaces.
    assert isinstance(data.get("proof_exceptions"), list)
    assert isinstance(data.get("code_owned_surfaces"), list)
    assert data["proof_exceptions"], "at least one proof exception must be classified"
    assert data["code_owned_surfaces"], (
        "at least one code-owned surface must be classified"
    )


def test_AC8_13_131_every_classified_entry_links_an_owner_and_issue() -> None:
    """AC-testing.governance.7: AC8.13.131: every classified entry names an id, owner, reason, and issue."""
    violations = gec.validate_registry(REGISTRY)
    assert violations == [], "\n".join(violations)


def test_AC8_13_131_gate_rejects_unclassified_or_unsourced_entries(
    tmp_path: Path,
) -> None:
    """AC8.13.131: the gate fails entries missing category/owner/issue fields."""
    bad = tmp_path / "governance-exceptions.yaml"
    bad.write_text(
        "version: 1\n"
        "exceptions: []\n"
        "proof_exceptions:\n"
        "  - id: missing-fields\n"  # no owner / reason / issue
        "code_owned_surfaces: []\n",
        encoding="utf-8",
    )
    violations = gec.validate_registry(bad)
    assert violations, "registry with an unsourced proof exception must be rejected"


def test_AC8_13_131_gate_main_passes_on_real_registry() -> None:
    """AC8.13.131: the committed registry passes the gate end-to-end."""
    assert gec.main([str(REGISTRY)]) == 0
