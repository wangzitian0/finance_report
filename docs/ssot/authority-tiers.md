# AC Authority Tiers

> **SSOT Key**: `authority_tiers`

This document owns the **authority-tier** vocabulary: the attribute that records
**how a module is built along one axis — who produces its result and how tightly
code constrains the LLM**. The tier is a **module-design property**, declared once
on a package's [`PackageContract`](../../common/governance/package_contract.py);
every AC the package owns *inherits* it.

> **A tier is NOT a per-record confidence.** "How confident are we in *this one*
> extracted row?" is a runtime number on a result, handled by reconciliation /
> review flows. "How is this *module* built?" is its tier. They are different
> axes — do not conflate them.

The payoff is direct: **a module's tier dictates what KIND of proof is valid for
its ACs.** Tying the testing strategy to authority stops us from demanding a
bit-exact golden assertion for an LLM-owned mapping (impossible) or accepting a
smoke test for a money calculation (unsafe).

## The axis and the four permanent tiers

There is **one axis**: how much of the result the LLM produces, and how tightly
code boxes it in. Two binary cuts — *does code or the LLM produce the used
result* (hard vs soft) × *how strong is the code discipline* — give four
permanent tiers:

| Code | Name (中文) | Produces the result | Reproducible? | Typical modules |
|------|-------------|---------------------|---------------|-----------------|
| **PC** | 纯代码 pure-code | **Code**, no LLM | Bit-level, fully reproducible | money/accounting, dedup, validation, persistence, reporting-calc, **recording a human decision/label** |
| **CP** | 代码为主·LLM辅助 code-primary | **Code**; the LLM only assists within strict code constraints on the I/O and decisions | Reproducible once the config/knobs are pinned | model/strategy selection feeding a deterministic parser; LLM-tuned thresholds with deterministic scoring |
| **LP** | LLM为主·代码守门 LLM-primary | **The LLM**; code validates its format/invariants and may reject, never produces | Not reproducible but DETECTABLE | extraction, OCR, classification, brokerage CSV→canonical mapping |
| **PL** | 纯LLM pure-LLM | **The LLM**, with no validation | Not required | advisor narrative, chat answer/suggestion text |

The **hard/soft** cut (who produces the used artifact) falls between CP and LP —
the same "who emits" test as before: code computes it and the LLM only turned
knobs → **CP**; the LLM emits it and code only validates/constrains → **LP**.

### HU is not a permanent tier — it is "undecided"

The legacy vocabulary had a fifth code, **HU** (人来判定). In the module-design
model it is **not a peer tier**: it means *the module's tier has not been decided
yet*. It is represented by a `draft` package with `tier=None` and **MUST resolve
to one of PC/CP/LP/PL before the package goes `active`** (see the rule below).

There is deliberately **no permanent "human" tier**, because:

- **Genuine human review is narrow and is an *input*.** The only place a person
  truly adjudicates is where reconciliation does not match and a human decides or
  labels. The matching engine is PC/CP (deterministic scoring); the human's
  decision is an *input* to a PC module that records it — exactly like an
  uploaded file or an FX rate is an input. The proof is a deterministic
  assertion that the **evidence chain** is surfaced and the chosen label is
  applied correctly — not an assertion of the human's outcome.
- So "a human decides" never describes *how a module is built*; it describes a
  runtime input the module consumes.

## Tier is a module property — one package, one tier

Because the tier describes construction, it lives on the **package**, not on each
AC:

- `PackageContract.tier` is the single declaration; ACs inherit it.
- **One package = one tier.** A module that genuinely both *emits via the LLM*
  and *computes deterministically* is two bounded contexts — split it into two
  packages (LP's definition already includes the code-side validation gate, so a
  well-formed LP package does not need a separate PC tier for its guard).

### The shipped-package rule (replaces the per-AC ratchet for packages)

> **`status="active"` (or `"deprecated"`) ⟹ `tier ∈ {PC, CP, LP, PL}`.**
> Only a `draft` package may leave `tier=None` (the "undecided" / legacy `HU`
> state). `PackageContract` enforces this at construction, so a *shipped untyped
> package is unrepresentable*.

## tier -> valid proof type

This matrix is the operative contract: which proof shape is *valid* evidence for
an AC under a package at each tier. Its single machine mirror is
`TIER_VALID_PROOF_KINDS` in `common/governance/package_contract.py` (the same
matrix `PackageContract` and `check_ac_proof_kind` both enforce).

| Tier | Valid proof | NOT valid |
|------|-------------|-----------|
| **PC** | Deterministic exact-assertion / property test; bit-level reproducible | — |
| **CP** | Test asserts the **code's final decision** is correct; the LLM suggestion may vary and is **not** asserted | Asserting the LLM suggestion text |
| **LP** | Invariant/property test + graded eval + provenance | Exact "golden" assertions on the LLM output |
| **PL** | Quality/smoke eval + guardrail assertions (must not touch numbers) | Reproducibility / exact-match requirements |
| **HU** *(legacy/undecided)* | Test asserts the **evidence chain** is present (evidence + options surfaced) | Asserting the human's outcome |

The rule with teeth: **an LP/PL behavior MUST NOT be proven by an exact golden
assertion** — LLM-emitted output has no golden oracle. The `HU` row applies only
to the handful of pre-package ACs still carrying the legacy marker; new packages
do not use it.

## Cross-tier MUST rules

Hard rules a module's tier must respect — the safety boundary between the
deterministic core and the LLM surface:

1. **No LLM-sourced financial truth without a deterministic oracle.** LP/PL
   output MUST cross a PC oracle (validation/guard) before it is persisted as
   financial truth. An LLM never writes a ledger number unchecked.
2. **PC stays pure.** A PC module MUST NOT depend on an LLM client; its outcome
   is produced and proven by deterministic code alone.
3. **PL owns no money.** A PL module MUST NOT source a number or persist
   financial facts; its deliverable is narrative/UX text with low blast radius.
4. **One package = one tier.** A package whose behaviors span tiers is too coarse
   and MUST be split (e.g. an LLM extractor that also validates-then-persists is
   an LP package whose guard is its code-side validation, not a PC package).

### Enforcing rule 2 structurally — the tier-import guard (phase 3)

Rule 2 ("PC stays pure") has a *structural* half that is checkable statically:
a deterministic financial-truth (PC) module MUST NOT **import** the LLM layer.
`tools/check_tier_imports.py` (impl `common/ssot/check_tier_imports.py`) makes
this a deterministic gate, AST-based and direct-import-only, complementing the
per-AC `{proof:KIND}` gate. On `main` today no protected module imports the LLM
layer, so the gate starts GREEN — it is a guard against regression.

The contract (the checker is the machine-checkable mirror of this list):

- **Protected PC / financial-truth module set:** everything under
  `apps/backend/src/money/**` and `apps/backend/src/ledger/**`, the journal model
  `apps/backend/src/models/journal.py`, and the deterministic services
  `deduplication.py`, `accounting.py`, `account_service.py`,
  `investment_accounting.py`, `statement_posting.py`, the `reporting/**`
  package, `reporting_calc.py`, `reporting_snapshot.py`, `validation.py`,
  `statement_validation.py`, `fx.py` / `fx_revaluation.py` / `fx_transfer.py` /
  `fx_transfer_discovery.py`, `portfolio.py`, `performance.py`,
  `performance_report.py`, and `allocation.py`.
- **Forbidden import targets:** the project's LLM layer (`src.llm` /
  `apps.backend.src.llm`) and any raw LLM SDK / provider client — `litellm`,
  `openrouter`, `anthropic`, `openai` — including any submodule of those
  (prefix match on dotted-path boundaries, so `src.llmx` does not match).

Detection is **direct imports only** for v1 (both `import X` and
`from X import …`, including the parent-package spelling `from src import llm`
which pulls `src.llm` into scope); transitive import-graph following is a
documented follow-up.
A protected glob that resolves to no file also fails the gate, so the curated set
cannot silently shrink as the tree evolves.

## How a tier is declared

**Primary (package model):** on the `PackageContract`, once per package:

```python
CONTRACT = PackageContract(
    name="counter",
    klass="platform",
    status="active",
    tier="PC",        # the whole package's authority tier; every AC inherits it
    ...
)
```

`common/ssot/generate_ac_registry.py` reads this package tier statically (AST) and
stamps it onto every AC in the package's `roadmap`, so the registry value carries
the inherited tier.

**Legacy (EPIC-table source, being phased out):** a pre-package AC declares its
tier inline at the definition site with a `{tier:XX}` marker, where `XX` is one of
`PC | CP | HU | LP | PL`:

```text
| AC3.1.1 | Parse DBS PDF {tier:LP} | `test_...` | `extraction/test_pdf_parsing.py` | P0 |
| AC3.2.1 | Balance Validation (Pass) {tier:PC} | `test_balance_valid` | ... | P0 |
```

`tools/generate_ac_registry.py` strips the marker and lifts the tier into the AC's
registry value. As modules become packages, their ACs move into the package
`roadmap` and the marker (including any legacy `HU`) goes away.

## How a proof kind is declared (and enforced)

Each AC declares the KIND of proof its tests provide with a `proof_kind` (on the
`ACRecord`, or a `{proof:KIND}` marker in the legacy EPIC source). `KIND` is one
of `property | invariant | eval | exact | evidence | smoke`. When an AC declares
**no** proof kind, it defaults to its (package) tier's canonical valid kind, so
the value is always a kind the matrix accepts:

| Tier | Default proof kind |
|------|--------------------|
| PC | `exact` |
| CP | `exact` |
| LP | `property` |
| PL | `smoke` |
| HU *(legacy)* | `evidence` |

`PackageContract` validates each roadmap AC's `proof_kind` against the package
tier at construction (a violating contract fails to import);
`tools/check_ac_proof_kind.py` enforces the same matrix for the legacy EPIC
source. The rule with teeth is **an LP/PL AC's proof_kind MUST NOT be `exact`**.
Statically verifying the referenced test's runtime *shape* (so a golden assertion
mislabeled `property` is rejected) is a documented follow-up.

`proof_kind` is a different axis from the critical-proof matrix's `trust_mode`
(`deterministic_pr` / `llm_ocr_post_merge` / `hybrid`): `trust_mode` says which
CI stage may be trusted to run a proof, while `proof_kind` says what SHAPE of
proof is valid for the module's authority tier. They are orthogonal.

## Adoption (non-breaking)

- **Package model:** the shipped-package rule above is enforced at construction —
  no ratchet needed, because an active package physically cannot omit its tier.
- **Legacy EPIC source:** ~1830 ACs predate this attribute, adopted via a
  **shrink-only debt ratchet** in [`ac-tier-baseline.json`](./ac-tier-baseline.json).
  `tools/check_ac_tier_baseline.py` is id-based: it fails only when a genuinely
  new AC (id absent from the baseline) lacks a tier; the baseline may only shrink.
  Each module that becomes a package moves its ACs into the package `roadmap`,
  which removes them from the untagged debt.

## CODE/LLM bit (counted view)

The five tiers above collapse, for measurement, into **one bit per AC plus a
per-package ratio** — and the bit is **detected from the AC's test shape**, not
declared:

- `LLM` — the AC's test exercises the record/replay (cassette) harness.
- `CODE` — a structured-input deterministic test, no LLM in the loop.

Mapping from the five tiers: `PC`,`CP` → `CODE`; `LP`,`PL` → `LLM`; `HU` stays an
orthogonal human-decision tag, not part of the ratio.

Each package (currently an EPIC) gets an `LLM-share = #LLM / (#CODE + #LLM)` placed
into four bands:

| Band | LLM-share | Meaning |
|------|-----------|---------|
| `CODE-ONLY` | 0 | enforceable: no LLM permitted (money math, ledger) |
| `CODE-LED` | 0–50 | measured; ratchet caps drift |
| `LLM-LED` | 50–100 | measured; ratchet caps drift |
| `LLM-ONLY` | 100 | enforceable: no hardcode permitted (narrative) |

Because the bit is detected, the band is **computed, not argued**. The base
library is `common/ssot/authority_classifier.py` and the runnable counter is
`tools/authority_counter.py` (snapshot: `authority-distribution.json`). Two
orthogonal rules still apply: an `LLM` value entering financial truth must pass a
code check (cross-tier rule 2), and an `LLM` AC must have a cassette. Migrating
the existing `{tier:XX}` markers onto this counted view is a follow-up.

## Follow-ups (out of scope here)

- Migrating the remaining EPIC-table ACs into package `roadmap`s (the ratchet
  shrinks as packages adopt them); retiring the `{tier:XX}` marker and the `HU`
  code once no EPIC AC carries them.
- A derived **module-level tier view** (already the natural unit now that tier is
  per-package).
- Upgrading the proof-kind gate from asserting the *declared* `proof_kind` to
  statically inspecting the referenced test's shape (e.g. rejecting an
  exact-golden assertion mislabeled `property` on an LP AC).

## Related

- [tdd.md](./tdd.md) — EPIC -> AC -> Test workflow that this attribute extends.
- [EPIC-026](../project/EPIC-026.ac-authority-tiers.md) — the EPIC that introduces tiers.
- [ai.md](./ai.md), [extraction.md](./extraction.md) — domains where LP/PL behaviors concentrate.
- [`common/governance/package_contract.py`](../../common/governance/package_contract.py) — the machine source of `PackageTier` and the proof matrix.
