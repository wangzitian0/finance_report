# EPIC-026: AC Authority Tiers

> **Status**: 🚧 In Progress
> **Vision Anchor**: `decision-7-tech-stack`
> **Owner**: Platform / Governance
> **Phase**: Hardening
> **Dependencies**: EPIC-008 (Testing Strategy), EPIC-014 (TTD Transformation)

---

## 🎯 Objective

Make **authority** a first-class, machine-readable attribute of every acceptance
criterion. Each AC records *who holds final decision authority over the behavior
it describes* — deterministic code, a human, or an LLM — as one of five tiers
(`PC / CP / HU / LP / PL`). The tier is an attribute of the AC's behavior, not of
a file: the AC is the unit of intent, so the same module can host PC and LP
behaviors and each AC still carries its own tier.

The crucial payoff: **an AC's tier dictates what KIND of proof is valid for it**,
tying the testing strategy to intent. The tier vocabulary, the cross-tier MUST
rules, and the tier→valid-proof matrix are owned by the SSOT
([authority-tiers.md](../ssot/authority-tiers.md)); this EPIC references that
contract rather than restating it.

---

## 🧭 Plan (STAR)

### Situation
- **Anchor**: `decision-7-tech-stack` — code-owned, machine-checkable single
  sources of truth over duplicated prose.
- **Gap**: The system mixes a strict deterministic core (money, accounting,
  validation, persistence) with an LLM surface (extraction, classification, chat
  advisor). Recent staging incidents traced to treating LLM-owned behaviors as if
  they were reproducible code: golden assertions on non-deterministic mappings,
  LLM output reaching financial truth without a deterministic oracle, and review
  routing tested for an outcome instead of an evidence chain. There was no
  attribute on an AC saying which discipline of proof applies.

### Tasks
- **Dictionary**: define the five tiers + cross-tier MUST rules + proof matrix in
  SSOT.
- **Schema**: let an AC declare `tier` at its definition site; flow it into the
  generated registry value.
- **Gate**: a non-breaking ratchet so new/changed ACs declare a tier while ~1830
  legacy untagged ACs ratchet down over time.
- **First batch**: tag the EPICs central to the strict↔LLM design discussion.

### Actions
1. Author [authority-tiers.md](../ssot/authority-tiers.md); register it in
   `docs/ssot/MANIFEST.yaml` (`authority_tiers`).
2. Extend the EPIC AC declaration with a `{tier:XX}` marker and teach
   `tools/generate_ac_registry.py` to lift it into the AC value.
3. Add `tools/check_ac_tier_baseline.py` + `docs/ssot/ac-tier-baseline.json`
   (shrink-only untagged-debt baseline), wired into the AC/lint gate; add a test.
4. Tag every AC in the first-batch EPICs and shrink the baseline accordingly.

### Result
- Every AC can carry a tier; new/changed ACs must; the proof discipline for each
  AC is now explicit and machine-readable.

---

## ✅ Scope

- **In**: tier vocabulary (SSOT), AC `tier` schema + generator support, the
  shrink-only ratchet gate + its test, and a first batch of tagged EPICs.
- **Out**: full backfill of the remaining untagged ACs; the derived module-level
  tier view; CI enforcement of tier→proof-type (rejecting an exact-golden proof
  for an LP AC, or a number-touching assertion for a PL AC). These are explicit
  follow-ups. No application/runtime logic changes.

---

## ✅ Must Have

- The five-tier vocabulary, cross-tier MUST rules, and tier→valid-proof matrix
  exist in one SSOT owner.
- An AC can declare its tier next to its text and the tier becomes a first-class
  registry attribute.
- New or changed ACs cannot silently skip a tier; the legacy untagged debt can
  only shrink.
- The first-batch EPICs have every AC tagged.

---

## 🌟 Nice to Have

- A derived dashboard of tier coverage per EPIC / per module.
- A `tier`-aware proof linter.

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.

### AC26.1 — Tier vocabulary & proof matrix in SSOT

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.1.1 | The SSOT `authority-tiers.md` defines exactly the five tiers (PC/CP/HU/LP/PL), the cross-tier MUST rules, and the tier→valid-proof matrix, and is registered as the single owner of `authority_tiers` in the manifest {tier:PC} | `test_AC26_1_1_ssot_defines_five_tiers_and_proof_matrix` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

### AC26.2 — AC schema carries the tier

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.2.1 | An AC declaring a `{tier:XX}` marker at its definition site flows `tier: XX` into its generated registry value, with the marker stripped from the description; an undeclared tier and an invalid code are both ignored, not errors {tier:PC} | `test_AC26_2_1_tier_marker_flows_into_registry_value` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

### AC26.3 — Non-breaking ratchet gate

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.3.1 | The tier ratchet fails when an AC absent from the untagged-debt baseline lacks a tier (new/changed debt), passes when every untagged AC is in the baseline, and `--update` only shrinks the baseline (never launders fresh untagged debt) {tier:PC} | `test_AC26_3_1_tier_ratchet_is_shrink_only_and_blocks_new_debt` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

### AC26.4 — First-batch backfill

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.4.1 | Every AC in the first-batch EPICs (003, 006, 021, 023) declares a valid tier, and none of those ACs remains in the untagged-debt baseline {tier:PC} | `test_AC26_4_1_first_batch_epics_fully_tagged_and_off_baseline` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|----------|--------------|--------|
| Tier vocabulary + proof matrix in one SSOT owner | `authority-tiers.md` + manifest `authority_tiers` | 🚧 |
| AC schema carries `tier` | `{tier:XX}` flows into registry value | 🚧 |
| Ratchet is non-breaking | Untagged-debt baseline shrink-only | 🚧 |
| First batch tagged | EPIC-003/006/021/023 fully tiered | 🚧 |

### 🚫 Not Acceptable

- A hard "every AC must have a tier" check that fails CI on the legacy untagged ACs.
- A tier marker leaking into the AC description text.
- An AC declaring more than one tier (one AC = one tier).
- Any application/runtime logic change.

---

## 🔗 References

- SSOT: [authority-tiers.md](../ssot/authority-tiers.md)
- Untagged-debt baseline: [ac-tier-baseline.json](../ssot/ac-tier-baseline.json)
- Generator: `tools/generate_ac_registry.py` · Gate: `tools/check_ac_tier_baseline.py`
- Workflow context: [tdd.md](../ssot/tdd.md)
