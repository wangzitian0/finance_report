"""Product E2E owner test for EPIC-026 (AC authority tiers).

EPIC-026 is a docs/governance EPIC: its "product" is the authority-tier pipeline
itself. This Tier-agnostic E2E drives the REAL repo end to end — EPIC markdown
-> ``generate_ac_registry`` -> registry value -> ``check_ac_tier_baseline``
ratchet — proving the whole chain works against the actual checked-in EPIC docs
and baseline, not a fixture. It needs no app/DB/browser, so it is safe anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.meta.extension import check_ac_tier_baseline as tier_gate
from common.meta.extension import generate_ac_registry as gar

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.e2e
def test_authority_tier_pipeline_end_to_end_epic026() -> None:
    """EPIC-026 / AC-authority.2.1 + AC-authority.3.1 + AC-authority.4.1: the real tier pipeline holds.

    GIVEN the actual EPIC docs and the committed untagged-debt baseline
    WHEN building the registry and running the ratchet against the live repo
    THEN tagged ACs expose a valid tier, no tagged AC remains in the debt
    baseline, and the ratchet reports no NEW untagged debt (the gate is green).
    """
    entries = gar.build_registry_entries(epic_source=ROOT / "docs" / "project")
    baseline = tier_gate.load_baseline(ROOT / "docs/ssot/ac-tier-baseline.json")
    untagged = tier_gate.current_untagged(ROOT)

    tagged = {ac: e["tier"] for ac, e in entries.items() if e.get("tier")}
    assert tagged, "first batch must have produced tagged ACs"
    assert all(tier in gar.AC_TIERS for tier in tagged.values())

    # A tagged AC is never in the untagged-debt baseline (the ratchet shrank it).
    assert not (set(tagged) & baseline)

    # The live ratchet sees no new untagged debt -> the CI gate is green.
    findings = tier_gate.evaluate(baseline, untagged)
    assert findings["new_untagged"] == []
