# EPIC-026: AC Authority Tiers

> **Status**: 🚧 In Progress
> **Vision Anchor**: `decision-7-tech-stack`
> **Owner**: Platform / Governance
> **Phase**: Hardening
> **Dependencies**: EPIC-008 (Testing Strategy), EPIC-014 (TTD Transformation)

---

## 🎯 Objective

Make **authority** a machine-readable property of every acceptance criterion:
*does deterministic code or the LLM produce the result the AC proves?* The
surviving model is the **detected CODE/LLM bit** — one bit per AC, **detected
from the AC's test shape** (a record/replay cassette test ⇒ `LLM`; a
structured-input deterministic test ⇒ `CODE`), rolled up per package (EPIC) into
an `LLM-share` and one of four bands (`CODE-ONLY` / `CODE-LED` / `LLM-LED` /
`LLM-ONLY`). Because the bit is detected, the band is **computed, not argued**.
The vocabulary, the cross-cutting MUST rules, and the structural import guard are
owned by the SSOT ([authority-tiers.md](../ssot/authority-tiers.md)); this EPIC
references that contract rather than restating it.

> **Superseded — declared tiers removed.** An earlier phase of this EPIC declared
> authority as a **5-tier attribute** (`PC / CP / HU / LP / PL`) on each AC /
> `PackageContract`, with a tier→valid-proof matrix and inline `{tier:XX}` /
> `{proof:KIND}` markers, enforced by a tier ratchet, a proof-kind gate, and a
> tier-AST-literal gate. That **declared** model and all of those gates were
> **removed** in favor of the detected CODE/LLM model (AC26.9). Only the
> structural import guard (AC26.7) and the CODE/LLM classifier (AC26.9) survive;
> the AC blocks below are kept for historical traceability and marked
> accordingly.

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
- **Dictionary**: define the CODE/LLM bit, the per-package LLM-share + four
  bands, the cross-cutting MUST rules, and the structural import guard in SSOT.
- **Classifier**: detect the CODE/LLM bit from each AC's test shape.
- **Counter**: roll the bits up per package into an LLM-share + band snapshot.
- **Structural guard**: keep a deterministic financial-truth (CODE-ONLY) module
  from importing the LLM layer.

### Actions
1. Author [authority-tiers.md](../ssot/authority-tiers.md); register it in
   `docs/ssot/MANIFEST.yaml` (`authority_tiers`).
2. Implement `common/ssot/authority_classifier.py` (the per-AC CODE/LLM bit) and
   `tools/authority_counter.py` (the per-package LLM-share + band snapshot).
3. Implement `common/ssot/check_tier_imports.py` (the structural guard).
4. **Removed**: the declared `{tier:XX}` / `{proof:KIND}` markers, the tier
   ratchet (`check_ac_tier_baseline`), the proof-kind matrix gate
   (`check_ac_proof_kind`), and the tier-AST-literal gate
   (`check_tier_ast_literal`).

### Result
- Every AC carries a detected CODE/LLM bit; each package has a computed
  LLM-share and band; financial-truth modules are statically barred from
  importing the LLM layer.

---

## ✅ Scope

- **In (surviving)**: the CODE/LLM vocabulary + four bands + cross-cutting MUST
  rules in SSOT; the per-AC classifier and per-package counter (AC26.9); the
  structural import guard (AC26.7); the invariant-observability metrics (AC26.8).
- **Removed**: the declared 5-tier model (`PC / CP / HU / LP / PL`) on the AC /
  `PackageContract`, the tier→valid-proof matrix, the inline `{tier:XX}` /
  `{proof:KIND}` markers, the tier ratchet, the proof-kind matrix gate, and the
  tier-AST-literal gate (AC26.1–AC26.6). These were superseded by the detected
  CODE/LLM model.
- **Out**: wiring the counter to a blocking per-package drift ratchet; transitive
  import-graph following for the structural guard. These are explicit follow-ups.
  No application/runtime logic changes.

---

## ✅ Must Have

- The CODE/LLM vocabulary, four bands, cross-cutting MUST rules, and the
  structural import guard exist in one SSOT owner.
- Every AC's authority is detected from its test shape (never declared); each
  package has a computed LLM-share and band.
- A deterministic financial-truth (CODE-ONLY) module cannot import the LLM layer.

---

## 🌟 Nice to Have

- A blocking per-package LLM-share drift ratchet.
- A derived dashboard of band coverage per EPIC / per module.

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.

### AC26.1 — ~~Tier vocabulary & proof matrix in SSOT~~ (REMOVED — declared-tier model superseded by CODE/LLM)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| ~~AC26.1.1~~ | ~~The SSOT `authority-tiers.md` defines exactly the five tiers (PC/CP/HU/LP/PL), the cross-tier MUST rules, and the tier→valid-proof matrix.~~ **Removed**: the SSOT now defines only the detected CODE/LLM model. | — | — | — |

### AC26.2 — ~~AC schema carries the tier~~ (REMOVED — `{tier:XX}` marker dropped)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| ~~AC26.2.1~~ | ~~An AC declaring a `{tier:XX}` marker flows `tier: XX` into its generated registry value.~~ **Removed**: authority is detected from test shape, never declared. | — | — | — |

### AC26.3 — ~~Non-breaking ratchet gate~~ (REMOVED — tier ratchet `check_ac_tier_baseline` deleted)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| ~~AC26.3.1~~ | ~~The tier ratchet fails when an AC absent from the untagged-debt baseline lacks a tier.~~ **Removed** with the declared-tier model. | — | — | — |

### AC26.4 — ~~First-batch backfill~~ (REMOVED — no tiers to backfill)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| ~~AC26.4.1~~ | ~~Every AC in the first-batch EPICs declares a valid tier.~~ **Removed** with the declared-tier model. | — | — | — |

### AC26.5 — ~~Tier→proof-kind matrix is enforced~~ (REMOVED — proof-kind gate `check_ac_proof_kind` deleted)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| ~~AC26.5.1~~ | ~~An AC declares the KIND of its proof via a `{proof:KIND}` marker and the gate enforces the tier→proof matrix.~~ **Removed**: there is no proof-kind matrix in the CODE/LLM model. | — | — | — |

### AC26.6 — ~~First-batch LP/CP ACs carry a valid-kind proof~~ (REMOVED)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| ~~AC26.6.1~~ | ~~The first-batch LP/HU/PL ACs each declare a matrix-valid `proof_kind`.~~ **Removed** with the proof-kind matrix. | — | — | — |

### AC26.7 — Structural rule enforced: financial-truth modules must not import the LLM layer (SURVIVES)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.7.1 | Deterministic financial-truth (CODE-ONLY) modules are statically proven free of LLM-layer imports — the cross-cutting structural MUST rule (`authority-tiers.md`) made deterministic. `tools/check_tier_imports.py` (impl `common/ssot/check_tier_imports.py`) AST-parses a curated protected set (`money/**`, `ledger/**`, the journal model, and the deterministic dedup/accounting/posting/reporting/validation/fx/portfolio/performance/allocation services) and fails on any direct import of the LLM layer (`src.llm` / `apps.backend.src.llm`) or a raw provider SDK (`litellm`/`openrouter`/`anthropic`/`openai`), including submodules (dotted-prefix match). The real tree passes today (guard against regression); a synthetic protected-style module importing `src.llm` is detected; a glob that resolves to no file also fails so the protected set cannot silently shrink. Direct imports only for v1 (transitive following is a follow-up). | `test_AC26_7_1_real_tree_has_no_llm_imports_in_protected_modules` | `tests/tooling/test_tier_imports.py` | P0 |

### AC26.8 — Financial-invariant violations are detectable, not silent (phase 4)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.8.1 | Financial-invariant violations emit structured, queryable metrics so a slipped violation is never silent — closing the original retrospective's observability gap. During a statement parse, a balance mismatch, a per-currency NAV self-check failure, a running-balance chain break, and a within-document dedup collapse each emit a WARNING-level structured log plus a `finance.invariant.violation` counter (via the existing `telemetry_metrics` mechanism) labelled by `kind` and an anonymized `institution_class` (`bank`/`brokerage`, never a real institution name or account id). Within-document dedup collapse is detected as a deterministic conservation property — `extracted-rows − distinct dedup hashes` over a SINGLE parse's freshly-built rows, computed BEFORE any DB upsert — so it catches the #1254 silent row-loss class (defense-in-depth, since #1254 is fixed) while legitimate CROSS-document dedup (a re-uploaded statement collapsing against already-persisted rows) can never trip it. This is purely detection/observability plus a non-blocking metadata flag: statement routing, status, confidence, approval gates, and persistence outcomes are UNCHANGED — a balance-invalid bank statement still routes to `PARSED`/review. | `test_AC26_8_1_balance_invalid_parse_keeps_routing_and_emits_metric` | `apps/backend/tests/extraction/test_invariant_observability.py` | P0 |

### AC26.9 — CODE/LLM authority is counted from test shape (phase 5)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC26.9.1 | A base library classifies every AC as `CODE` or `LLM` **detected from its test shape** (a record/replay cassette test ⇒ `LLM`; a structured-input deterministic test ⇒ `CODE`), and a counter aggregates each package (EPIC) into an `LLM-share = #LLM / (#CODE + #LLM)` mapped to one of four bands — `CODE-ONLY` (`s = 0`), `CODE-LED` (`0 < s < 50`), `LLM-LED` (`50 ≤ s < 100`), `LLM-ONLY` (`s = 100`). Classification is detected, never declared, so the band is computed not argued; the counter writes a deterministic snapshot and reports the unresolved-test rate. See `docs/ssot/authority-tiers.md` §CODE/LLM bit. | `test_AC26_9_1_band_boundaries`, `test_AC26_9_1_test_shape_classifies_code_vs_llm`, `test_AC26_9_1_counter_runs_over_repo_and_is_well_formed` | `tests/tooling/test_authority_classifier.py` | P0 |

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|----------|--------------|--------|
| CODE/LLM vocabulary + bands + MUST rules in one SSOT owner | `authority-tiers.md` + manifest `authority_tiers` | ✅ |
| Authority detected from test shape, never declared | `common/ssot/authority_classifier.py` | ✅ |
| Per-package LLM-share + band computed | `tools/authority_counter.py` → `authority-distribution.json` | ✅ |
| Financial-truth modules barred from importing the LLM layer | `tools/check_tier_imports.py` (AC26.7) | ✅ |

### 🚫 Not Acceptable

- Re-introducing a declared authority attribute (`{tier:XX}`, `PackageContract.tier`).
- A CODE-ONLY package containing an LLM-classified AC, or vice versa.
- Any application/runtime logic change.

---

## 🔗 References

- SSOT: [authority-tiers.md](../ssot/authority-tiers.md)
- CODE/LLM snapshot: [authority-distribution.json](../ssot/authority-distribution.json)
- Classifier: `common/ssot/authority_classifier.py` · Counter: `tools/authority_counter.py`
- Structural guard: `common/ssot/check_tier_imports.py` (`tools/check_tier_imports.py`)
- Workflow context: [tdd.md](../ssot/tdd.md)
