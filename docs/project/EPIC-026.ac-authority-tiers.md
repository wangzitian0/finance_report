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

### AC26.1 — Tier vocabulary & proof matrix in SSOT

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.1.1 | The SSOT `authority-tiers.md` defines exactly the five tiers (CODE-ONLY/CODE-LED/HU/LLM-LED/LLM-ONLY), the cross-tier MUST rules, and the tier→valid-proof matrix, and is registered as the single owner of `authority_tiers` in the manifest {tier:CODE-ONLY} | `test_AC26_1_1_ssot_defines_five_tiers_and_proof_matrix` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

### AC26.2 — AC schema carries the tier

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.2.1 | An AC declaring a `{tier:XX}` marker at its definition site flows `tier: XX` into its generated registry value, with the marker stripped from the description; an undeclared tier and an invalid code are both ignored, not errors {tier:CODE-ONLY} | `test_AC26_2_1_tier_marker_flows_into_registry_value` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

### AC26.3 — Non-breaking ratchet gate

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.3.1 | The tier ratchet fails when an AC absent from the untagged-debt baseline lacks a tier (new/changed debt), passes when every untagged AC is in the baseline, and `--update` only shrinks the baseline (never launders fresh untagged debt) {tier:CODE-ONLY} | `test_AC26_3_1_tier_ratchet_is_shrink_only_and_blocks_new_debt` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

### AC26.4 — First-batch backfill

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.4.1 | Every AC in the first-batch EPICs (003, 006, 021, 023) declares a valid tier, and none of those ACs remains in the untagged-debt baseline {tier:CODE-ONLY} | `test_AC26_4_1_first_batch_epics_fully_tagged_and_off_baseline` | `tests/tooling/test_ac_authority_tiers.py` | P0 |

### AC26.5 — Tier→proof-kind matrix is enforced (phase 2)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.5.1 | An AC declares the KIND of its proof via a `{proof:KIND}` marker (KIND ∈ property/invariant/eval/exact/evidence/smoke), parsed alongside `{tier:XX}`, stripped from the description, and lifted into the registry as `proof_kind` (defaulting to the tier's canonical valid kind when unmarked); the enforcement gate then asserts, **for tier-tagged ACs only** (untagged ACs ignored, so it is non-breaking), that the declared kind matches the tier→proof matrix — in particular an **LLM-LED AC's proof_kind MUST NOT be `exact`**, HU must be `evidence`, and LLM-ONLY must not be exact. The gate asserts the *declared* kind; verifying the referenced test's runtime shape is a documented follow-up. {tier:CODE-ONLY} {proof:property} | `test_AC26_5_1_proof_kind_marker_flows_and_gate_enforces_matrix` | `tests/tooling/test_ac_proof_kind.py` | P0 |

### AC26.6 — First-batch LLM-LED/CODE-LED ACs carry a valid-kind proof

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.6.1 | The first-batch LLM-LED/HU/LLM-ONLY ACs retrofitted in this phase (the LLM-LED extraction ACs AC3.1.1/AC3.5.7/AC3.5.19, the HU review ACs AC3.3.2/AC3.5.10/AC3.6.4, the LLM-ONLY suggestion ACs AC6.2.3/AC6.2.4) each declare a matrix-valid `proof_kind`; the LLM-LED ACs carry an invariant/property proof (the balance-chain `opening + ΣIN − ΣOUT ≈ closing` detector and the #1254 dedup conservation property), so the whole tier-tagged set passes the proof-kind gate. {tier:CODE-ONLY} {proof:property} | `test_AC26_6_1_first_batch_lp_acs_carry_invariant_proof` | `tests/tooling/test_ac_proof_kind.py` | P0 |

### AC26.7 — Cross-tier structural rule enforced (phase 3)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.7.1 | CODE-ONLY/financial-truth modules are statically proven free of LLM-layer imports — the cross-tier structural MUST rule ("CODE-ONLY stays pure", `authority-tiers.md` rule 2) made deterministic. `tools/check_tier_imports.py` (impl `common/authority/check_tier_imports.py`) AST-parses a curated protected set (`money/**`, `ledger/**`, the journal model, and the deterministic dedup/accounting/posting/reporting/validation/fx/portfolio/performance/allocation services) and fails on any direct import of the LLM layer (`src.llm` / `apps.backend.src.llm`) or a raw provider SDK (`litellm`/`openrouter`/`anthropic`/`openai`), including submodules (dotted-prefix match). The real tree passes today (guard against regression); a synthetic protected-style module importing `src.llm` is detected; a glob that resolves to no file also fails so the protected set cannot silently shrink. Direct imports only for v1 (transitive following is a follow-up). {tier:CODE-ONLY} {proof:property} | `test_AC26_7_1_real_tree_has_no_llm_imports_in_protected_modules` | `tests/tooling/test_tier_imports.py` | P0 |

### AC26.8 — Financial-invariant violations are detectable, not silent (phase 4)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.8.1 | Financial-invariant violations emit structured, queryable metrics so a slipped violation is never silent — closing the original retrospective's observability gap. During a statement parse, a balance mismatch, a per-currency NAV self-check failure, a running-balance chain break, and a within-document dedup collapse each emit a WARNING-level structured log plus a `finance.invariant.violation` counter (via the existing `telemetry_metrics` mechanism) labelled by `kind` and an anonymized `institution_class` (`bank`/`brokerage`, never a real institution name or account id). Within-document dedup collapse is detected as a deterministic conservation property — `extracted-rows − distinct dedup hashes` over a SINGLE parse's freshly-built rows, computed BEFORE any DB upsert — so it catches the #1254 silent row-loss class (defense-in-depth, since #1254 is fixed) while legitimate CROSS-document dedup (a re-uploaded statement collapsing against already-persisted rows) can never trip it. This is purely detection/observability plus a non-blocking metadata flag: statement routing, status, confidence, approval gates, and persistence outcomes are UNCHANGED — a balance-invalid bank statement still routes to `PARSED`/review. {tier:CODE-ONLY} {proof:property} | `test_AC26_8_1_balance_invalid_parse_keeps_routing_and_emits_metric` | `apps/backend/tests/extraction/test_invariant_observability.py` | P0 |

### AC26.9 — CODE/LLM authority is counted from test shape (phase 5)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.9.1 | A base library classifies every AC as `CODE` or `LLM` **detected from its test shape** (a record/replay cassette test ⇒ `LLM`; a structured-input deterministic test ⇒ `CODE`), and a counter aggregates each package (EPIC) into an `LLM-share = #LLM / (#CODE + #LLM)` mapped to one of four bands — `CODE-ONLY` (`s = 0`), `CODE-LED` (`0 < s < 50`), `LLM-LED` (`50 ≤ s < 100`), `LLM-ONLY` (`s = 100`). Classification is detected, never declared, so the band is computed not argued; the counter writes a deterministic snapshot and reports the unresolved-test rate. See `docs/ssot/authority-tiers.md` §CODE/LLM bit. {tier:CODE-ONLY} {proof:property} | `test_AC26_9_1_band_boundaries`, `test_AC26_9_1_test_shape_classifies_code_vs_llm`, `test_AC26_9_1_counter_runs_over_repo_and_is_well_formed` | `tests/tooling/test_authority_classifier.py` | P0 |

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
