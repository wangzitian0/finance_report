"""Tests for EPIC-026 phase 2: tier->proof-kind marker + enforcement gate.

Covers:
- AC26.5.1 — the {proof:KIND} marker flows into the registry value (with the
  tier-aware default) and the gate enforces the tier->proof matrix for
  tier-tagged ACs only (LP cannot be exact; HU must be evidence; PL not exact).
- AC26.6.1 — the first-batch LP ACs carry an invariant/property proof (the
  #1254 balance-chain + dedup-conservation regression).
"""

from __future__ import annotations

from pathlib import Path

from common.ssot import check_ac_proof_kind as proof_gate
from common.ssot import generate_ac_registry as gar

ROOT = Path(__file__).resolve().parents[2]


def _write_epic(epic_dir: Path, fname: str, content: str) -> None:
    epic_dir.mkdir(parents=True, exist_ok=True)
    (epic_dir / fname).write_text(content, encoding="utf-8")


def test_AC26_5_1_proof_kind_marker_flows_and_gate_enforces_matrix(
    tmp_path, monkeypatch
) -> None:
    """AC26.5.1: {proof:KIND} flows into the value; gate enforces the matrix."""
    epic_dir = tmp_path / "docs" / "project"
    overrides = tmp_path / "docs" / "ac_registry_overrides.yaml"
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text("version: '1.0'\ngroups: {}\n", encoding="utf-8")
    _write_epic(
        epic_dir,
        "EPIC-003.statement-parsing.md",
        # LP with an explicit invariant proof -> valid.
        "| AC3.1.1 | Parse DBS PDF {tier:LP} {proof:invariant} | t | f | P0 |\n"
        # PC with no proof marker -> defaults to exact -> valid.
        "| AC3.1.2 | Parse CSV {tier:PC} | t | f | P0 |\n"
        # LP with no proof marker -> defaults to property (NOT exact) -> valid.
        "| AC3.1.3 | OCR default {tier:LP} | t | f | P0 |\n"
        # HU with no proof marker -> defaults to evidence -> valid.
        "| AC3.1.4 | Review queue {tier:HU} | t | f | P0 |\n"
        # Untagged AC -> no proof_kind, ignored by the gate.
        "| AC3.1.5 | No tier {proof:exact} | t | f | P0 |\n",
    )
    monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
    monkeypatch.setattr(gar, "OVERRIDES", str(overrides))

    entries = gar.build_registry_entries(epic_source=epic_dir, overrides=overrides)

    # The marker flows in, stripped from the description.
    assert entries["AC3.1.1"]["proof_kind"] == "invariant"
    assert "{proof" not in entries["AC3.1.1"]["description"]
    assert entries["AC3.1.1"]["description"] == "Parse DBS PDF"
    # Tier-aware defaults.
    assert entries["AC3.1.2"]["proof_kind"] == "exact"  # PC default
    assert entries["AC3.1.3"]["proof_kind"] == "property"  # LP default (not exact)
    assert entries["AC3.1.4"]["proof_kind"] == "evidence"  # HU default
    # Untagged AC carries no proof_kind (gate ignores it) even with a stray marker.
    assert "proof_kind" not in entries["AC3.1.5"]
    assert "tier" not in entries["AC3.1.5"]

    # The valid fixture passes the gate.
    assert proof_gate.proof_kind_violations(tmp_path) == []

    # Now the rule that must fire: an LP AC marked exact is rejected.
    _write_epic(
        epic_dir,
        "EPIC-003.statement-parsing.md",
        "| AC3.1.1 | Parse DBS PDF {tier:LP} {proof:exact} | t | f | P0 |\n",
    )
    violations = proof_gate.proof_kind_violations(tmp_path)
    assert any("AC3.1.1" in v and "exact" in v for v in violations), violations

    # HU marked with a non-evidence kind is rejected.
    _write_epic(
        epic_dir,
        "EPIC-003.statement-parsing.md",
        "| AC3.1.4 | Review queue {tier:HU} {proof:exact} | t | f | P0 |\n",
    )
    hu_violations = proof_gate.proof_kind_violations(tmp_path)
    assert any("AC3.1.4" in v for v in hu_violations), hu_violations

    # PL marked exact is rejected (PL must not assert numbers/exact output).
    _write_epic(
        epic_dir,
        "EPIC-006.ai-advisor.md",
        "| AC6.2.3 | Suggestions {tier:PL} {proof:exact} | t | f | P0 |\n",
    )
    pl_violations = proof_gate.proof_kind_violations(tmp_path)
    assert any("AC6.2.3" in v for v in pl_violations), pl_violations


def test_AC26_5_1_matrix_mirrors_ssot_and_real_repo_passes() -> None:
    """AC26.5.1: the live repo passes the gate (every tier-tagged AC is valid)."""
    assert proof_gate.proof_kind_violations(ROOT) == []
    # The matrix mirror is the five tiers, and LP/PL never accept exact.
    assert set(proof_gate.VALID_PROOF_KINDS) == set(gar.AC_TIERS)
    assert "exact" not in proof_gate.VALID_PROOF_KINDS["LP"]
    assert "exact" not in proof_gate.VALID_PROOF_KINDS["PL"]
    assert proof_gate.VALID_PROOF_KINDS["HU"] == frozenset({"evidence"})


def test_AC26_6_1_first_batch_lp_acs_carry_invariant_proof() -> None:
    """AC26.6.1: the retrofitted first-batch LP/HU/PL ACs declare valid kinds."""
    entries = gar.build_registry_entries(epic_source=ROOT / "docs" / "project")

    # The LP extraction ACs carry an invariant/property proof (#1254 regression).
    assert entries["AC3.1.1"]["proof_kind"] == "invariant"
    assert entries["AC3.5.7"]["proof_kind"] == "invariant"
    assert entries["AC3.5.19"]["proof_kind"] == "property"
    # HU review ACs carry an evidence proof.
    for ac_id in ("AC3.3.2", "AC3.5.10", "AC3.6.4"):
        assert entries[ac_id]["proof_kind"] == "evidence", ac_id
    # PL suggestion ACs carry a smoke proof.
    for ac_id in ("AC6.2.3", "AC6.2.4"):
        assert entries[ac_id]["proof_kind"] == "smoke", ac_id

    # None of the LP ACs is exact (the matrix rule that must hold).
    for ac_id in ("AC3.1.1", "AC3.5.7", "AC3.5.19"):
        assert entries[ac_id]["tier"] == "LP"
        assert entries[ac_id]["proof_kind"] != "exact"

    # The new EPIC-026 governance ACs are themselves tagged + valid.
    assert entries["AC26.5.1"]["tier"] == "PC"
    assert entries["AC26.6.1"]["tier"] == "PC"
    assert proof_gate.proof_kind_violations(ROOT) == []
