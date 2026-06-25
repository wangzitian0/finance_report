# Package migration standard (the target architecture)

> The standard the whole repo migrates **to**: ~10 high-cohesion packages, each
> code-owning its contract + docs, so EPIC tables and most SSOT prose are absorbed
> and the repo becomes contract-driven. Owned by the `meta` package (this file is
> its prose). The only authored horizontal docs that survive are `vision.md` and
> each package's `readme.md`.

## Why

We keep auditing **drift** between EPIC AC tables / central SSOT indexes and the
code, because central mirrors must be hand-synced and don't stay in sync. The fix
is to delete the mirror: **the contract is the single source**, governance is
**computed**, and meta-info is **aggregated**, never hand-maintained.

## The ~10 packages

Two cross-cutting governors (parallel peers, not super-packages) + the value
foundation + the financial data flow + the technical substrate:

| package | base deps | extension deps | own info (base) | governance domain (extension) |
|---|---|---|---|---|
| **meta** | — | (reads every contract) | DDD domain/package structure, interfaces, tooling | every package is well-formed: structure / deps / acyclic / migration progress |
| **audit** | — | ledger, extraction, portfolio, reporting | financial base types (Money/Ratio/Quantity/UnitPrice/FX) + invariants + confidence/provenance + trace records | global numeric correctness + accounting consistency + end-to-end traceability |
| **middleware** | — | — | event bus / outbox / workflow / pipeline / counter / identity | how domain packages plug in: delivery atomicity, auth boundary |
| **llm** | — | middleware | provider abstraction, cassette, stream | LLM calls are deterministically replayable; no secret in argv |
| **extraction** | audit | middleware, llm | auto-extracted types (Statement/Transaction/Confidence/Dedup) | source→fact balance chain, dedup conservation |
| **portfolio** | audit | middleware | manually-entered types + UI (Position/ManualValuation/ESOP/Dividend) | manual data clearly labeled, valuation traceable |
| **reconciliation** | audit, extraction, portfolio | middleware, ledger | matching/review (Match/Review/Correction/ProcessingAccount) | record↔evidence consistency, two-stage review, in-transit visibility |
| **ledger** | audit | reconciliation | double-entry (Account/JournalEntry/Line/Balance) | debits = credits (See: docs/ssot/accounting.md#entry-balance), only reconciled facts post |
| **reporting** | audit | ledger, portfolio | reports (ReportPackage/FrameworkPolicy/Snapshot/Readiness) | report lines reconcile, framework 1:1 |
| **advisor** | audit | middleware, llm, reporting, portfolio | AI advisor (Session/Suggestion/AnnualizedIncome) | advice never becomes a ledger number unchecked |

**Financial data flow:** `(extraction [auto] + portfolio [manual]) → reconciliation → ledger → reporting → advisor`.

**meta / audit symmetry** — both are foundational *and* governing, one for **form**,
one for **number**: everyone's `base` depends on `meta.base` (the package model)
and on `audit.base` (Money), so `meta.extension` reaches every package (governs
structure) and `audit.extension` reaches the financial flow (governs the numbers).
This is why `value` folds into `audit`: the financial base types and their
governance are one concern.

## Internal layering (replaces kernel/platform/core and types/ops/store/api)

Every package is, in implementation, three sub-layers — a **menu**, not a mandate
(base always; extension only with cross-package edges; data only with consumers/ACs):

- **base** — self-contained definitions + pure logic; **no I/O, no cross-package
  code**. Imports only other packages' `base`. Forms a **downward DAG** (acyclic).
- **extension** — the impure edges: cross-package associations, I/O, ORM, event
  bus, transport/LLM adapters. Its own import surface; forms its own DAG (typically
  the **transpose/upward** direction). Separate from base, so `A.base → B.base`
  and `B.extension → A.extension` coexist **without a cycle**.
- **data** — metadata only: consumers (reverse deps) + governance tasks (roadmap
  ACs, invariants). Free (no code-import constraint), because declarations can't
  form import cycles.

Rule enforced by `check_package_contract`: **never up, never sideways-cyclic** —
no import of a higher layer; same-layer edges allowed when declared **and** the
graph stays acyclic (a global cycle check, per layer). "10 packages" is really
~30 governed units (10 × 3 layers).

## Acceptance criteria: `AC-<package>.<entity>.<seq>`

ACs hang off **entities**, not a flat EPIC number — e.g. `AC-ledger.journal-entry.3`,
`AC-extraction.statement.2`, `AC-audit.global-invariant.1`. They live in the
package contract's `roadmap`; `meta`'s data layer aggregates them — **never
mirrored into an EPIC table**.

## Frontend

FE is **not** a separate package tree. Each package's contract owns **one
`interface` + one set of conformance `vectors`**; `implementations["be"]` and
`["fe"]` are two conforming implementations of that single contract, kept
consistent by the shared vectors. **The FE decides its own implementation**;
consistency is the vectors' job. Backend-only packages set `fe=None`.

## Directory structure (where files go)

Every package uses the same layers (`base` / `extension` / `data`); only **where
the code lives** differs. Pick **one** of three layouts — do not invent others.

### 1. Domain / capability package (default — counter, ledger, reporting, …)

Spec in `common/`, code in `apps/`. `data` is metadata in `contract.py`, not a dir.

```
common/<pkg>/                         spec + review surface
  __init__.py                         re-exports CONTRACT
  contract.py                         interface · roles=[base,extension] · invariants · roadmap(ACs)
  readme.md  todo.md                  prose (absorbs the package's SSOT) + worklist
apps/backend/src/<pkg>/               BE implementation  (implementations["be"])
  __init__.py                         __all__ == contract.interface
  base/        types/ ops/ ports      pure core — downward DAG, no I/O
  extension/   sql.py  api/           impure edges — ORM / transport / cross-package
apps/frontend/src/lib/<pkg>/          FE implementation (optional; implementations["fe"])
apps/backend/tests/<pkg>/             behavior tests
tests/tooling/test_<pkg>_package.py   contract / invariant tests
```

### 2. Value-type narrow-waist package (the audit value language)

Canonical code in `common/`, BE + FE mirrors, conformance vectors keep them in
sync. Use **only** for a cross-runtime leaf value language (needed by BE *and* FE).

```
common/<pkg>/
  __init__.py  contract.py  readme.md  todo.md
  conformance/vectors.json            shared BE/FE parity vectors (the consistency guarantee)
  base/                               canonical pure value types + ops
  extension/                          wire/db serialization edges
apps/backend/src/<pkg>/               BE mirror — conforms to interface + vectors
apps/frontend/src/lib/<pkg>/          FE mirror — conforms to interface + vectors
```

### 3. The governing package: `meta` (common-only)

`meta` is its own implementation; everything lives under `common/meta/`. Its
`data/` is the one physical data layer — the computed index that replaces the
hand-maintained MANIFEST / registry.

```
common/meta/
  __init__.py  contract.py  readme.md  todo.md  migration-standard.md
  base/                               the model — PackageContract, tiers, proof matrix
  extension/                          the gate — check_package_contract (governs every package)
  data/                               the computed meta-index (registry · AC index · coverage)
```

### Choosing the layout

- BE-only domain / capability → **layout 1** (code in `apps/`).
- cross-runtime leaf value language (BE + FE + conformance vectors) → **layout 2**.
- the governing `meta` package → **layout 3** (common-only).

Layout 1 is live in `counter`; the value types already use layout 2; `meta` is
still flat and adopts layout 3 as it is refactored. New packages MUST match one
of these — the gate (`check_package_contract`) owns the `base↓ / extension↑` rule.

## Completion state (Definition of Done) — the migration unit is the AC

An EPIC is horizontal and a package is vertical, so they do not map 1:1. The
**migration unit is the AC, not the EPIC**:

1. **AC moved** — each AC is rewritten as `AC-<pkg>.<entity>.<seq>` in its owning
   package's `roadmap` and removed from the EPIC table.
2. **EPIC deleted** — only once **all** of an EPIC's ACs have been distributed
   into packages (a horizontal-only EPIC is reduced to a thin goal stub or removed).
3. **SSOT internalized** — the package's owned SSOT doc/concept moves into the
   package (readme/contract) and is removed from `docs/ssot/` + `MANIFEST.yaml`.
4. **Tests migrated** — tests live with the package; every `invariants[].test` /
   `roadmap[].test` resolves.
5. **Consumers repointed** — importers use the package's published `interface`
   (`__all__`), not its submodules/internals.
6. **Green** — `check_package_contract` + the package's own invariants pass.

Each package cutover is **one atomic PR** (never leave a single package half in
both an EPIC and a roadmap). Different packages may be old-or-new during the
overall migration; a single package is never half-migrated.

## Anti-mud-ball guard

The win is real only if `base` layers stay clean and `extension` layers stay
**thin**. `meta`'s data layer tracks each package's **extension fan-out**
(cross-package edge count) as a metric, so coupling that creeps back into a fat
extension is visible, not hidden.

## Migration order

1. **Step 0** — this standard (0a) + refactor `counter` into base/extension/data
   as the worked template, and extend `check_package_contract` to support the
   three-layer rule (additive; existing packages keep working). (0b)
2. **value → audit** fold (its own PR).
3. **ledger** (the prototype core cutover, already has a legacy `.contract.md`).
4. **extraction / portfolio / reconciliation / reporting** (the flow).
5. **advisor / llm / middleware / identity**.
6. **audit** consistency closeout (global invariants + cross-package ACs).
7. **Cleanup** — delete residual EPIC tables / SSOT, retire the central
   MANIFEST/registry gates once `meta`'s data layer is the computed index.

## Related

- [`readme.md`](./readme.md) — what a package is (the model).
- [`contract.py`](./contract.py) — the `meta` package's own contract.
- [`../../vision.md`](../../vision.md) — the only authored north-star.
