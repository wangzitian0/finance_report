"""Tests for EPIC-026 phase 2: tier->proof-kind marker + enforcement gate.

Covers:
- AC-authority.5.1 — the {proof:KIND} marker flows into the registry value (with the
  tier-aware default) and the gate enforces the tier->proof matrix for
  tier-tagged ACs only (LLM-LED cannot be exact; HU must be evidence; LLM-ONLY not exact).
- AC-authority.6.1 — the first-batch LLM-LED ACs carry an invariant/property proof (the
  #1254 balance-chain + dedup-conservation regression).
"""

from __future__ import annotations

from pathlib import Path

from common.meta.extension import check_ac_proof_kind as proof_gate
from common.meta.extension import generate_ac_registry as gar

ROOT = Path(__file__).resolve().parents[2]


def _write_epic(epic_dir: Path, fname: str, content: str) -> None:
    epic_dir.mkdir(parents=True, exist_ok=True)
    (epic_dir / fname).write_text(content, encoding="utf-8")


def test_AC26_5_1_proof_kind_marker_flows_and_gate_enforces_matrix(
    tmp_path, monkeypatch
) -> None:
    """AC-authority.5.1: {proof:KIND} flows into the value; gate enforces the matrix."""
    epic_dir = tmp_path / "docs" / "project"
    overrides = tmp_path / "docs" / "ac_registry_overrides.yaml"
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text("version: '1.0'\ngroups: {}\n", encoding="utf-8")
    _write_epic(
        epic_dir,
        "EPIC-003.statement-parsing.md",
        # LLM-LED with an explicit invariant proof -> valid.
        "| AC3.1.1 | Parse DBS PDF {tier:LLM-LED} {proof:invariant} | t | f | P0 | <!-- epic-owned: pending-package -->\n"
        # CODE-ONLY with no proof marker -> defaults to exact -> valid.
        "| AC3.1.2 | Parse CSV {tier:CODE-ONLY} | t | f | P0 | <!-- epic-owned: pending-package -->\n"
        # LLM-LED with no proof marker -> defaults to property (NOT exact) -> valid.
        "| AC3.1.3 | OCR default {tier:LLM-LED} | t | f | P0 | <!-- epic-owned: pending-package -->\n"
        # HU with no proof marker -> defaults to evidence -> valid.
        "| AC3.1.4 | Review queue {tier:HU} | t | f | P0 | <!-- epic-owned: pending-package -->\n"
        # Untagged AC -> no proof_kind, ignored by the gate.
        "| AC3.1.5 | No tier {proof:exact} | t | f | P0 | <!-- epic-owned: pending-package -->\n",
    )
    monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
    monkeypatch.setattr(gar, "OVERRIDES", str(overrides))

    entries = gar.build_registry_entries(epic_source=epic_dir, overrides=overrides)

    # The marker flows in, stripped from the description.
    assert entries["AC3.1.1"]["proof_kind"] == "invariant"
    assert "{proof" not in entries["AC3.1.1"]["description"]
    assert entries["AC3.1.1"]["description"] == "Parse DBS PDF"
    # Tier-aware defaults.
    assert entries["AC3.1.2"]["proof_kind"] == "exact"  # CODE-ONLY default
    assert entries["AC3.1.3"]["proof_kind"] == "property"  # LLM-LED default (not exact)
    assert entries["AC3.1.4"]["proof_kind"] == "evidence"  # HU default
    # Untagged AC carries no proof_kind (gate ignores it) even with a stray marker.
    assert "proof_kind" not in entries["AC3.1.5"]
    assert "tier" not in entries["AC3.1.5"]

    # The valid fixture passes the gate.
    assert proof_gate.proof_kind_violations(tmp_path) == []

    # Now the rule that must fire: an LLM-LED AC marked exact is rejected.
    _write_epic(
        epic_dir,
        "EPIC-003.statement-parsing.md",
        "| AC3.1.1 | Parse DBS PDF {tier:LLM-LED} {proof:exact} | t | f | P0 | <!-- epic-owned: pending-package -->\n",
    )
    violations = proof_gate.proof_kind_violations(tmp_path)
    assert any("AC3.1.1" in v and "exact" in v for v in violations), violations

    # HU marked with a non-evidence kind is rejected.
    _write_epic(
        epic_dir,
        "EPIC-003.statement-parsing.md",
        "| AC3.1.4 | Review queue {tier:HU} {proof:exact} | t | f | P0 | <!-- epic-owned: pending-package -->\n",
    )
    hu_violations = proof_gate.proof_kind_violations(tmp_path)
    assert any("AC3.1.4" in v for v in hu_violations), hu_violations

    # LLM-ONLY marked exact is rejected (LLM-ONLY must not assert numbers/exact output).
    _write_epic(
        epic_dir,
        "EPIC-006.ai-advisor.md",
        "| AC6.2.3 | Suggestions {tier:LLM-ONLY} {proof:exact} | t | f | P0 | <!-- epic-owned: pending-package -->\n",
    )
    pl_violations = proof_gate.proof_kind_violations(tmp_path)
    assert any("AC6.2.3" in v for v in pl_violations), pl_violations


def test_AC26_5_1_matrix_mirrors_ssot_and_real_repo_passes() -> None:
    """AC-authority.5.1: the live repo passes the gate (every tier-tagged AC is valid)."""
    assert proof_gate.proof_kind_violations(ROOT) == []
    # The matrix mirror is the five tiers, and LLM-LED/LLM-ONLY never accept exact.
    assert set(proof_gate.VALID_PROOF_KINDS) == set(gar.AC_TIERS)
    assert "exact" not in proof_gate.VALID_PROOF_KINDS["LLM-LED"]
    assert "exact" not in proof_gate.VALID_PROOF_KINDS["LLM-ONLY"]
    assert proof_gate.VALID_PROOF_KINDS["HU"] == frozenset({"evidence"})


def test_AC26_6_1_first_batch_lp_acs_carry_invariant_proof() -> None:
    """AC-authority.6.1: the retrofitted first-batch LLM-LED/HU/LLM-ONLY ACs declare valid kinds."""
    entries = gar.build_registry_entries(epic_source=ROOT / "docs" / "project")

    # The LLM-LED extraction ACs migrated into the package roadmap (#1421):
    # their proof kinds are asserted on the contract (the registry's source).
    from common.extraction.contract import CONTRACT as EXTRACTION_CONTRACT

    roadmap = {r.id: r for r in EXTRACTION_CONTRACT.roadmap}
    assert roadmap["AC-extraction.1.1"].proof_kind == "invariant"
    assert roadmap["AC-extraction.5.7"].proof_kind == "invariant"
    assert roadmap["AC-extraction.5.19"].proof_kind == "property"
    # The legacy HU review ACs (AC3.3.2/AC3.5.10/AC3.6.4) migrated into this
    # same roadmap 2026-07-14: their {tier:HU}{proof:evidence} marker predated
    # the tier->proof matrix and was never revisited — the underlying tests
    # are ordinary deterministic assertions, so they carry "property" under
    # the package's LLM-LED tier, not "evidence".
    for ac_id in ("AC-extraction.3.2", "AC-extraction.5.10", "AC-extraction.6.4"):
        assert roadmap[ac_id].proof_kind == "property", ac_id
    # The old LLM-ONLY/smoke suggestion ACs (AC6.2.3/AC6.2.4) migrated into the
    # advisor package roadmap (#1663) as AC-advisor.suggestions.1/.2 — on
    # inspection both tests are pure static-copy assertions with no LLM call,
    # so the migration corrected the miscalibrated tier/proof to
    # CODE-ONLY/property rather than copying "smoke" uncritically.
    from common.advisor.contract import CONTRACT as ADVISOR_CONTRACT

    advisor_roadmap = {r.id: r for r in ADVISOR_CONTRACT.roadmap}
    for ac_id in ("AC-advisor.suggestions.1", "AC-advisor.suggestions.2"):
        assert advisor_roadmap[ac_id].proof_kind == "property", ac_id

    # None of the LLM-LED ACs is exact (the matrix rule that must hold); the
    # package tier is LLM-LED for every roadmap AC.
    assert EXTRACTION_CONTRACT.tier == "LLM-LED"
    for ac_id in ("AC-extraction.1.1", "AC-extraction.5.7", "AC-extraction.5.19"):
        assert roadmap[ac_id].proof_kind != "exact"
