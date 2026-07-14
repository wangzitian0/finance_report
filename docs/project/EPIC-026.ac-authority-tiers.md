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
(`CODE-ONLY / CODE-LED / HU / LLM-LED / LLM-ONLY`). The tier is an attribute of the AC's behavior, not of
a file: the AC is the unit of intent, so the same module can host CODE-ONLY and LLM-LED
behaviors and each AC still carries its own tier.

The crucial payoff: **an AC's tier dictates what KIND of proof is valid for it**,
tying the testing strategy to intent. The tier vocabulary, the cross-tier MUST
rules, and the tier→valid-proof matrix are owned by the `meta` package (converged from `authority` in #1626;
[common/meta/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/meta/readme.md));
this EPIC references that contract rather than restating it.

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
1. Author the tier vocabulary (now internalized into the `meta` package
   after the #1626 authority→meta converge, [common/meta/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/meta/readme.md));
   register it in `docs/ssot/MANIFEST.yaml` (`authority_tiers`).
2. Extend the EPIC AC declaration with a `{tier:XX}` marker and teach
   `tools/generate_ac_registry.py` to lift it into the AC value.
3. Add `tools/check_ac_tier_baseline.py` + `common/meta/data/ac-tier-baseline.json`
   (shrink-only untagged-debt baseline), wired into the AC/lint gate; add a test.
4. Tag every AC in the first-batch EPICs and shrink the baseline accordingly.

### Result
- Every AC can carry a tier; new/changed ACs must; the proof discipline for each
  AC is now explicit and machine-readable.

---

## ✅ Scope

- **In (phase 1)**: tier vocabulary (SSOT), AC `tier` schema + generator support,
  the shrink-only ratchet gate + its test, and a first batch of tagged EPICs.
- **In (phase 2)**: a `{proof:KIND}` marker giving each AC a declared proof kind,
  generator support that lifts it into the registry (`proof_kind`, defaulting to
  the tier's canonical kind), and `tools/check_ac_proof_kind.py` enforcing the
  tier→proof matrix for **tier-tagged ACs only** (non-breaking) — the rule that
  must fire is **LLM-LED cannot be exact**. The first-batch LLM-LED/HU/LLM-ONLY ACs are
  retrofitted so each carries a matrix-valid proof (the LLM-LED extraction ACs gain
  invariant/property proofs that double as the #1254 money-bug regression).
- **Out**: full backfill of the remaining untagged ACs; the derived module-level
  tier view; upgrading the proof-kind gate from asserting the *declared* kind to
  inspecting the referenced test's runtime shape (e.g. statically rejecting an
  exact assertion mislabeled `property`). These are explicit follow-ups. No
  application/runtime logic changes.

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

> **`AC-authority.1.1`, `AC-authority.2.1`, `AC-authority.3.1`, `AC-authority.4.1`,
> `AC-authority.5.1`, `AC-authority.6.1`, and `AC-authority.7.1` are defined in the
> `meta` package (converged from `authority`, #1626), not here.** The authority-tier *system* ACs (phases 1–3) are
> homed in [`common/meta/contract.py`](../../common/meta/contract.py)'s
> `roadmap` under the package-scoped id scheme — the contract is their single
> definition source (resolved by `check_package_contract`). This EPIC stays the
> horizontal narrative. The phase-4 row below migrated too (migration closeout
> wave 2, #1663) to
> [`common/observability/contract.py`](../../common/observability/contract.py)'s
> `roadmap` as `AC-observability.18.1` — it's a metric-emission behavior, which
> observability already owns. The phase-5 row **remains here**:
> `AC26.9.1`'s proof test is itself marker-laden (it tests cassette
> detection), so homing it in the CODE-ONLY `meta` package would make that
> package's own tier-reconciliation gate read it as CODE-LED and fail.

### AC26.8 — Financial-invariant violations are detectable, not silent (phase 4)

*(This group's row removed — migrated above.)*

### AC26.9 — CODE/LLM authority is counted from test shape (phase 5)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.9.1 | A base library classifies every AC as `CODE` or `LLM` **detected from its test shape** (a record/replay cassette test ⇒ `LLM`; a structured-input deterministic test ⇒ `CODE`), and a counter aggregates each package into an `LLM-share` mapped to one of four bands — `CODE-ONLY` (`s = 0`), `CODE-LED` (`0 < s < 50`), `LLM-LED` (`50 ≤ s < 100`), `LLM-ONLY` (`s = 100`). Classification is detected, never declared, so the band is computed not argued. See `common/meta/readme.md` §CODE/LLM bit. {tier:CODE-ONLY} {proof:property} | `test_AC26_9_1_band_boundaries`, `test_AC26_9_1_test_shape_classifies_code_vs_llm` | `tests/tooling/test_authority_classifier.py` | P0 | <!-- epic-owned: horizontal -->

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

- SSOT: [common/meta/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/meta/readme.md)
  (the tier vocabulary, internalized into the `authority` package)
- Untagged-debt baseline: [ac-tier-baseline.json](../../common/meta/data/ac-tier-baseline.json)
- Generator: `tools/generate_ac_registry.py` · Gate: `tools/check_ac_tier_baseline.py`
- Workflow context: [tdd.md](../../common/testing/tdd.md)
