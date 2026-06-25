"""Tests for EPIC-026 AC authority tiers (vocabulary, schema, ratchet, backfill).

Covers:
- AC26.1.1 — the SSOT vocabulary + proof matrix + manifest ownership.
- AC26.2.1 — a {tier:XX} marker flows into the generated registry value.
- AC26.3.1 — the shrink-only untagged-debt ratchet gate.
- AC26.4.1 — the first-batch EPICs are fully tagged and off the baseline.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from common.authority import check_ac_tier_baseline as tier_gate
from common.ssot import generate_ac_registry as gar

ROOT = Path(__file__).resolve().parents[2]

FIRST_BATCH_EPICS = (3, 6, 21, 23)


def _write_epic(epic_dir: Path, fname: str, content: str) -> None:
    epic_dir.mkdir(parents=True, exist_ok=True)
    (epic_dir / fname).write_text(content, encoding="utf-8")


def test_AC26_1_1_ssot_defines_five_tiers_and_proof_matrix() -> None:
    """AC26.1.1: The five tiers, MUST rules, and proof matrix live in one SSOT owner."""
    doc = (ROOT / "docs/ssot/authority-tiers.md").read_text(encoding="utf-8")
    manifest = yaml.safe_load(
        (ROOT / "docs/ssot/MANIFEST.yaml").read_text(encoding="utf-8")
    )

    # Exactly the five tier codes are the canonical vocabulary.
    assert gar.AC_TIERS == ("CODE-ONLY", "CODE-LED", "LLM-LED", "LLM-ONLY", "HU")
    for code in gar.AC_TIERS:
        assert f"**{code}**" in doc

    # The tier->proof matrix and cross-tier MUST rules are present.
    assert "tier -> valid proof type" in doc
    assert "Cross-tier MUST rules" in doc
    # The defining proof-discipline statements per tier.
    assert "bit-level reproducible" in doc  # CODE-ONLY
    assert "evidence chain" in doc.lower()  # HU
    assert "golden" in doc.lower()  # LLM-LED: golden assertions are NOT valid

    # Single owner registered in the manifest.
    concept = manifest["concepts"]["authority_tiers"]
    assert concept["owner"] == "docs/ssot/authority-tiers.md"


def test_AC26_2_1_tier_marker_flows_into_registry_value(tmp_path, monkeypatch) -> None:
    """AC26.2.1: {tier:XX} flows into the value; bad/absent markers are ignored."""
    epic_dir = tmp_path / "docs" / "project"
    overrides = tmp_path / "docs" / "ac_registry_overrides.yaml"
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text("version: '1.0'\ngroups: {}\n", encoding="utf-8")
    _write_epic(
        epic_dir,
        "EPIC-003.statement-parsing.md",
        "| AC3.1.1 | Parse DBS PDF {tier:LLM-LED} | t | f | P0 |\n"
        "| AC3.1.2 | Parse CSV (DBS) {tier:CODE-ONLY} | t | f | P0 |\n"
        "| AC3.1.3 | No tier declared here | t | f | P0 |\n"
        "| AC3.1.4 | Bad tier {tier:ZZ} marker | t | f | P0 |\n",
    )
    monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
    monkeypatch.setattr(gar, "OVERRIDES", str(overrides))

    entries = gar.build_registry_entries(epic_source=epic_dir, overrides=overrides)

    assert entries["AC3.1.1"]["tier"] == "LLM-LED"
    assert entries["AC3.1.2"]["tier"] == "CODE-ONLY"
    # Marker is stripped from the description, never leaked.
    assert "{tier" not in entries["AC3.1.1"]["description"]
    assert entries["AC3.1.1"]["description"] == "Parse DBS PDF"
    # No marker -> no tier key (untagged).
    assert "tier" not in entries["AC3.1.3"]
    # An invalid code is not a recognised marker; the AC stays untagged and the
    # bogus token remains as plain description text (not a silent failure).
    assert "tier" not in entries["AC3.1.4"]


def test_AC26_3_1_tier_ratchet_is_shrink_only_and_blocks_new_debt(tmp_path) -> None:
    """AC26.3.1: New untagged debt fails; baseline only shrinks via --update."""
    baseline_path = tmp_path / "ac-tier-baseline.json"

    # Baseline tolerates one known-untagged AC; a second untagged AC is new debt.
    baseline = {"AC1.1.1"}
    untagged_now = {"AC1.1.1", "AC1.1.2"}

    findings = tier_gate.evaluate(baseline, untagged_now)
    assert findings["new_untagged"] == ["AC1.1.2"]  # the new/changed debt

    # An untagged set fully covered by the baseline produces no failure.
    assert tier_gate.evaluate({"AC1.1.1", "AC1.1.2"}, {"AC1.1.1"})["new_untagged"] == []

    # --update is shrink-only: a now-tagged AC (gone from untagged) is dropped,
    # and a brand-new untagged AC is NOT laundered into the baseline.
    ratcheted = tier_gate.ratcheted_baseline(
        {"AC1.1.1", "AC1.1.3"}, {"AC1.1.1", "AC9.9.9"}
    )
    assert ratcheted == {"AC1.1.1"}  # AC1.1.3 tagged -> dropped; AC9.9.9 not added

    # Round-trip the persisted baseline file (sorted, with the comment + version).
    tier_gate.write_baseline(baseline_path, {"AC2.1.1", "AC10.1.1"})
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["untagged"] == ["AC2.1.1", "AC10.1.1"]  # numeric sort
    assert tier_gate.load_baseline(baseline_path) == {"AC2.1.1", "AC10.1.1"}


def test_AC26_4_1_first_batch_epics_fully_tagged_and_off_baseline() -> None:
    """AC26.4.1: First-batch EPIC ACs all carry a valid tier and are off the baseline."""
    entries = gar.build_registry_entries(epic_source=ROOT / "docs" / "project")
    baseline = tier_gate.load_baseline(ROOT / "docs/ssot/ac-tier-baseline.json")

    batch = {
        ac_id: entry
        for ac_id, entry in entries.items()
        if int(entry.get("epic", 0)) in FIRST_BATCH_EPICS
    }
    assert batch, "first-batch EPICs must contribute ACs"

    for ac_id, entry in batch.items():
        assert entry.get("tier") in gar.AC_TIERS, f"{ac_id} has no valid tier"
        assert ac_id not in baseline, (
            f"{ac_id} is tagged but still in the debt baseline"
        )

    # The authority-tier-system ACs are homed in the authority package's roadmap
    # (keeping their numeric ids); EPIC-026 is infra, so they route to infra_registry.
    assert entries["AC26.1.1"]["tier"] == "CODE-ONLY"
    assert gar.classify_ac("AC26.1.1", entries["AC26.1.1"]) == "infra"
