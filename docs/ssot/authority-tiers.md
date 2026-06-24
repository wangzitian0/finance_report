# AC Authority — the detected CODE/LLM model

> **SSOT Key**: `authority_tiers`

This document owns the **authority** vocabulary for ACs: a single CODE-vs-LLM bit
per AC, **detected from the AC's test shape** (never declared), rolled up into a
per-package (per-EPIC) `LLM-share` and one of four bands. Authority answers one
question along one axis — *does deterministic code or the LLM produce the result
the AC proves?* — and it is computed, so the band is **measured, not argued**.

> **Authority is NOT a per-record confidence.** "How confident are we in *this
> one* extracted row?" is a runtime number on a result, handled by reconciliation
> / review flows. "Is this behavior produced by code or by the LLM?" is its
> authority bit. They are different axes — do not conflate them.

The machine source of truth is the classifier and counter, not this prose:

- **Classifier** — [`common/ssot/authority_classifier.py`](../../common/ssot/authority_classifier.py)
  decides the CODE/LLM bit for one AC from its test shape.
- **Counter** — [`tools/authority_counter.py`](../../tools/authority_counter.py)
  runs the classifier across the repo, computes each package's `LLM-share` and
  band, and writes the snapshot
  [`authority-distribution.json`](./authority-distribution.json).

## The one bit: CODE vs LLM, detected from the test

Each AC is classified as exactly one of:

- **`CODE`** — the AC's test is a structured-input deterministic test with **no
  LLM in the loop**. Code produces the result the AC proves; the test asserts it
  bit-exactly. Money math, accounting, dedup, validation, persistence, and
  reporting calculations live here.
- **`LLM`** — the AC's test drives the **record/replay (cassette) harness**: the
  LLM produces the result and the test exercises it through the recorded
  interaction. Extraction, OCR, classification, and advisor narrative live here.

The bit is **detected, not declared** — the classifier inspects whether the
referenced test uses the cassette/record-replay markers. An AC whose test shape
is unresolved is reported as such (the counter reports the unresolved rate); it
is **unclassified**, not a band.

## Per-package LLM-share and the four bands

The counter aggregates the per-AC bits for each package (currently an EPIC) into

```text
LLM-share  s = #LLM / (#CODE + #LLM)
```

and places the package in one of four bands:

| Band | LLM-share (`s`) | Meaning |
|------|-----------------|---------|
| `CODE-ONLY` | `s = 0` | **enforceable**: no LLM permitted (money math, ledger) |
| `CODE-LED` | `0 < s < 50` | measured; ratchet caps drift |
| `LLM-LED` | `50 ≤ s < 100` | measured; ratchet caps drift |
| `LLM-ONLY` | `s = 100` | **enforceable**: no hardcode permitted (narrative) |

The two extreme bands are **enforceable**: a `CODE-ONLY` package must contain no
LLM-classified AC, and an `LLM-ONLY` package must contain no hardcoded
deterministic result. The two middle bands are measured and ratcheted so the
share cannot silently drift.

## The structural rule: financial-truth modules must not import the LLM layer

The safety boundary between the deterministic core and the LLM surface has a
**structural half that is checkable statically**: a deterministic,
financial-truth (i.e. `CODE-ONLY`) module MUST NOT **import** the LLM layer.

[`common/ssot/check_tier_imports.py`](../../common/ssot/check_tier_imports.py)
makes this a deterministic gate — AST-based, direct-import-only. On `main` today
no protected module imports the LLM layer, so the gate starts GREEN; it is a
guard against regression.

The contract (the checker is the machine-checkable mirror of this list):

- **Protected deterministic / financial-truth module set:** everything under
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
documented follow-up. A protected glob that resolves to no file also fails the
gate, so the curated set cannot silently shrink as the tree evolves.

## Cross-cutting MUST rules

These bind regardless of band:

1. **No LLM-sourced financial truth without a deterministic oracle.** An `LLM`
   result MUST cross a deterministic (CODE) oracle — validation/guard — before it
   is persisted as financial truth. An LLM never writes a ledger number
   unchecked.
2. **A CODE-ONLY module stays pure.** Its outcome is produced and proven by
   deterministic code alone; it MUST NOT import the LLM layer (enforced
   structurally by the rule above).
3. **An `LLM` AC must have a cassette.** Its classification is detected from the
   record/replay harness; an `LLM` behavior with no cassette is not provable.

## Follow-ups (out of scope here)

- Wiring the counter into a blocking drift gate that ratchets each package's
  `LLM-share` so the middle bands cannot creep.
- Transitive import-graph following for the structural guard (v1 is
  direct-import only).

## Related

- [tdd.md](./tdd.md) — EPIC → AC → Test workflow that this attribute extends.
- [EPIC-026](../project/EPIC-026.ac-authority-tiers.md) — the EPIC that introduces
  the detected CODE/LLM authority model.
- [ai.md](./ai.md), [extraction.md](./extraction.md) — domains where `LLM`
  behaviors concentrate.
- [`common/ssot/authority_classifier.py`](../../common/ssot/authority_classifier.py)
  and [`tools/authority_counter.py`](../../tools/authority_counter.py) — the
  machine source of the CODE/LLM bit and the band rollup.
</content>
</invoke>
