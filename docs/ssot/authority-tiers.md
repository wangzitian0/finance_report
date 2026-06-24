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
| **CODE-ONLY** | 纯代码 pure-code | **Code**, no LLM | Bit-level, fully reproducible | money/accounting, dedup, validation, persistence, reporting-calc, **recording a human decision/label** |
| **CODE-LED** | 代码为主·LLM辅助 code-primary | **Code**; the LLM only assists within strict code constraints on the I/O and decisions | Reproducible once the config/knobs are pinned | model/strategy selection feeding a deterministic parser; LLM-tuned thresholds with deterministic scoring |
| **LLM-LED** | LLM为主·代码守门 LLM-primary | **The LLM**; code validates its format/invariants and may reject, never produces | Not reproducible but DETECTABLE | extraction, OCR, classification, brokerage CSV→canonical mapping |
| **LLM-ONLY** | 纯LLM pure-LLM | **The LLM**, with no validation | Not required | advisor narrative, chat answer/suggestion text |

The **hard/soft** cut (who produces the used artifact) falls between CODE-LED and LLM-LED —
the same "who emits" test as before: code computes it and the LLM only turned
knobs → **CODE-LED**; the LLM emits it and code only validates/constrains → **LLM-LED**.

### HU is not a permanent tier — it is "undecided"

The legacy vocabulary had a fifth code, **HU** (人来判定). In the module-design
model it is **not a peer tier**: it means *the module's tier has not been decided
yet*. It is represented by a `draft` package with `tier=None` and **MUST resolve
to one of CODE-ONLY/CODE-LED/LLM-LED/LLM-ONLY before the package goes `active`** (see the rule below).

There is deliberately **no permanent "human" tier**, because:

- **Genuine human review is narrow and is an *input*.** The only place a person
  truly adjudicates is where reconciliation does not match and a human decides or
  labels. The matching engine is CODE-ONLY/CODE-LED (deterministic scoring); the human's
  decision is an *input* to a CODE-ONLY module that records it — exactly like an
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
  packages (LLM-LED's definition already includes the code-side validation gate, so a
  well-formed LLM-LED package does not need a separate CODE-ONLY tier for its guard).

### The shipped-package rule (replaces the per-AC ratchet for packages)

> **`status="active"` (or `"deprecated"`) ⟹ `tier ∈ {CODE-ONLY, CODE-LED, LLM-LED, LLM-ONLY}`.**
> Only a `draft` package may leave `tier=None` (the "undecided" / legacy `HU`
> state). `PackageContract` enforces this at construction, so a *shipped untyped
> package is unrepresentable*.

### Structural assertions go in `invariants`, not `roadmap`

A package's **structural / governance guarantees** — interface == `__all__`,
"converges by role", layer-purity (types/ops never import the store/ORM),
"passes its own `check_package_contract`" — are NOT domain ACs. They are
deterministic properties of *how the package is assembled*, so they belong in
`PackageContract.invariants` (which carry no tier and are not constrained by the
tier→proof matrix), and the `roadmap` holds only the package's **domain** ACs,
which inherit the package tier.

This matters for **non-CODE-ONLY packages**: a structural assertion is inherently an
`exact`/deterministic test. If it sat in the `roadmap` of an **LLM-LED/LLM-ONLY** package it
would inherit that tier and the proof-matrix gate would reject it (LLM-LED/LLM-ONLY may not
be `exact`) — or force a dishonest mislabel. Putting it in `invariants` removes
the conflict. The matrix gate is therefore the enforcement: a structural `exact`
test wrongly placed in an LLM-LED roadmap fails CI, pushing it to `invariants` (no new
bespoke lint needed).

`common/counter` is the worked example: its `roadmap` is pure domain (key
validation, count, increment, query) while its structural guarantees
(`converges-by-role`, `types-layer-pure`, `ops-layer-pure`,
`passes-own-governance-gate`) are `invariants`. A CODE-ONLY package like `counter` would
not *fail* with structural ACs in its roadmap (CODE-ONLY permits `exact`), but it follows
the convention so it is a correct template to copy for LLM-LED/LLM-ONLY packages.

## tier -> valid proof type

This matrix is the operative contract: which proof shape is *valid* evidence for
an AC under a package at each tier. Its single machine mirror is
`TIER_VALID_PROOF_KINDS` in `common/governance/package_contract.py` (the same
matrix `PackageContract` and `check_ac_proof_kind` both enforce).

| Tier | Valid proof | NOT valid |
|------|-------------|-----------|
| **CODE-ONLY** | Deterministic exact-assertion / property test; bit-level reproducible | — |
| **CODE-LED** | Test asserts the **code's final decision** is correct; the LLM suggestion may vary and is **not** asserted | Asserting the LLM suggestion text |
| **LLM-LED** | Invariant/property test + graded eval + provenance | Exact "golden" assertions on the LLM output |
| **LLM-ONLY** | Quality/smoke eval + guardrail assertions (must not touch numbers) | Reproducibility / exact-match requirements |
| **HU** *(legacy/undecided)* | Test asserts the **evidence chain** is present (evidence + options surfaced) | Asserting the human's outcome |

The rule with teeth: **an LLM-LED/LLM-ONLY behavior MUST NOT be proven by an exact golden
assertion** — LLM-emitted output has no golden oracle. The `HU` row applies only
to the handful of pre-package ACs still carrying the legacy marker; new packages
do not use it.

## Cross-tier MUST rules

Hard rules a module's tier must respect — the safety boundary between the
deterministic core and the LLM surface:

1. **No LLM-sourced financial truth without a deterministic oracle.** LLM-LED/LLM-ONLY
   output MUST cross a CODE-ONLY oracle (validation/guard) before it is persisted as
   financial truth. An LLM never writes a ledger number unchecked.
2. **CODE-ONLY stays pure.** A CODE-ONLY module MUST NOT depend on an LLM client; its outcome
   is produced and proven by deterministic code alone.
3. **LLM-ONLY owns no money.** A LLM-ONLY module MUST NOT source a number or persist
   financial facts; its deliverable is narrative/UX text with low blast radius.
4. **One package = one tier.** A package whose behaviors span tiers is too coarse
   and MUST be split (e.g. an LLM extractor that also validates-then-persists is
   an LLM-LED package whose guard is its code-side validation, not a CODE-ONLY package).

### Enforcing rule 2 structurally — the tier-import guard (phase 3)

Rule 2 ("CODE-ONLY stays pure") has a *structural* half that is checkable statically:
a deterministic financial-truth (CODE-ONLY) module MUST NOT **import** the LLM layer.
`tools/check_tier_imports.py` (impl `common/authority/check_tier_imports.py`) makes
this a deterministic gate, AST-based and direct-import-only, complementing the
per-AC `{proof:KIND}` gate. On `main` today no protected module imports the LLM
layer, so the gate starts GREEN — it is a guard against regression.

The contract (the checker is the machine-checkable mirror of this list):

- **Protected CODE-ONLY / financial-truth module set:** everything under
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
    tier="CODE-ONLY",        # the whole package's authority tier; every AC inherits it
    ...
)
```

`common/ssot/generate_ac_registry.py` reads this package tier statically (AST) and
stamps it onto every AC in the package's `roadmap`, so the registry value carries
the inherited tier.

**Legacy (EPIC-table source, being phased out):** a pre-package AC declares its
tier inline at the definition site with a `{tier:XX}` marker, where `XX` is one of
`CODE-ONLY | CODE-LED | HU | LLM-LED | LLM-ONLY`:

```text
| AC3.1.1 | Parse DBS PDF {tier:LLM-LED} | `test_...` | `extraction/test_pdf_parsing.py` | P0 |
| AC3.2.1 | Balance Validation (Pass) {tier:CODE-ONLY} | `test_balance_valid` | ... | P0 |
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
| CODE-ONLY | `exact` |
| CODE-LED | `exact` |
| LLM-LED | `property` |
| LLM-ONLY | `smoke` |
| HU *(legacy)* | `evidence` |

`PackageContract` validates each roadmap AC's `proof_kind` against the package
tier at construction (a violating contract fails to import);
`tools/check_ac_proof_kind.py` enforces the same matrix for the legacy EPIC
source. The rule with teeth is **an LLM-LED/LLM-ONLY AC's proof_kind MUST NOT be `exact`**.
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

This is the **measured** mirror of the declared `PackageContract.tier`: the same
**hard/soft cut** of the four permanent tiers, but **detected per-AC from its test
shape** rather than declared on the package.

- `CODE` — the hard side (`CODE-ONLY`, `CODE-LED`): a structured-input deterministic test, no
  LLM in the loop.
- `LLM` — the soft side (`LLM-LED`, `LLM-ONLY`): the AC's test exercises the record/replay
  (cassette) harness.
- An undecided/`draft` package (legacy `HU`, `tier=None`) is **unclassified**, not
  a band — it has not resolved its tier yet.

Each package (currently an EPIC) gets an `LLM-share = #LLM / (#CODE + #LLM)` placed
into four bands:

| Band | LLM-share (`s`) | Meaning |
|------|-----------------|---------|
| `CODE-ONLY` | `s = 0` | enforceable: no LLM permitted (money math, ledger) |
| `CODE-LED` | `0 < s < 50` | measured; ratchet caps drift |
| `LLM-LED` | `50 ≤ s < 100` | measured; ratchet caps drift |
| `LLM-ONLY` | `s = 100` | enforceable: no hardcode permitted (narrative) |

Because the bit is detected, the band is **computed, not argued** — so it serves
as a **cross-check on the declared `PackageContract.tier`**: a package declared on
the hard side (`CODE-ONLY`/`CODE-LED`) but measuring `LLM` ACs is drift to flag. The base
library is `common/authority/authority_classifier.py` and the runnable counter is
`tools/authority_counter.py` (snapshot: `authority-distribution.json`). The
cross-tier MUST rules still bind (an `LLM` value entering financial truth crosses a
CODE-ONLY oracle; an `LLM` AC must have a cassette). Wiring the counter to the
`PackageContract` declarations as a blocking drift gate is a follow-up.

## Follow-ups (out of scope here)

- Migrating the remaining EPIC-table ACs into package `roadmap`s (the ratchet
  shrinks as packages adopt them); retiring the `{tier:XX}` marker and the `HU`
  code once no EPIC AC carries them.
- A derived **module-level tier view** (already the natural unit now that tier is
  per-package).
- Upgrading the proof-kind gate from asserting the *declared* `proof_kind` to
  statically inspecting the referenced test's shape (e.g. rejecting an
  exact-golden assertion mislabeled `property` on an LLM-LED AC).

## Related

- [tdd.md](./tdd.md) — EPIC -> AC -> Test workflow that this attribute extends.
- [EPIC-026](../project/EPIC-026.ac-authority-tiers.md) — the EPIC that introduces tiers.
- [ai.md](./ai.md), [extraction.md](./extraction.md) — domains where LLM-LED/LLM-ONLY behaviors concentrate.
- [`common/governance/package_contract.py`](../../common/governance/package_contract.py) — the machine source of `PackageTier` and the proof matrix.
