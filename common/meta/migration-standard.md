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
- **data** — the **read-model / projection** (CQRS sense): the computed view over
  the write side — consumers (reverse deps) + governance tasks (roadmap ACs,
  invariants) + the meta-index. A **leaf sink**: it imports `base`, and nothing in
  `base`/`extension` imports it, so the write side never depends on its own read
  model.

### The DDD building blocks → layer (the `units` taxonomy)

The layer is the **universal purity axis** (every package, domain or tooling). For
a *domain* package, each unit is additionally one of the eight DDD tactical
building blocks, and its `kind` decides its layer. That mapping is **code**
(`common/meta/base/package_contract.py` → `KIND_LAYER`), so the table can never
drift from what the gate checks:

| Building block | Layer | Cycle-breaking mechanism |
|---|---|---|
| Value Object | base | A — leaf, only depended-on |
| Entity | base | A — composes VOs, one-way |
| Aggregate Root | base | A + C — refer to other aggregates **by id** |
| Factory (pure) | base | A |
| Domain Event (record) | base | C — publisher & subscriber depend only on the event type |
| **Repository** | **port=base / impl=extension** | **B** — dependency inversion |
| Domain Service (cross-aggregate) | extension | A — `extension → base`, one-way |
| Event publish / Bus | extension | C — runtime registry, no compile edge |
| Projection | data | read-model, leaf sink |

The acyclicity is held by three mechanisms (the gate enforces A and B statically;
C is a convention with a partial static guard):

- **A — layer split / transpose.** No import of a higher layer; `base` never
  imports `extension`/`data`; cross-package edges flip to the transpose direction
  (`A.base → B.base` with `B.extension → A.extension`).
- **B — dependency inversion (repository).** A repository's abstract **port** lives
  in `base` (what the pure core depends on); its concrete **adapter** lives in
  `extension`. The gate requires the split.
- **C — id-reference + events.** Aggregates reference each other **by id**, not by
  object, and cross-aggregate effects go through a **Domain Event** on the bus
  (a runtime registry) — so there is no compile-time edge between aggregates or
  between publisher and subscriber. (Convention; the gate guards the data-sink and
  layer-purity halves of it, not the id-reference itself.)

Rule enforced by `check_package_contract`: **never up, never sideways-cyclic** —
no import of a higher layer; same-layer edges allowed when declared **and** the
graph stays acyclic (a global cycle check, per layer); each declared `unit` sits in
its kind's layer; a repository splits port/adapter; `data` stays a sink. "10
packages" is really ~30 governed units (10 × 3 layers).

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

## Where files go — contract vs implementation (there is no "layout")

There are **two levels of contract**, and **one uniform package shape**; physical
placement *falls out* of them — it is not a separate choice.

- **Project-level contract** — `meta` owns it: the `PackageContract` schema, the
  dependency DAG, the composition rules (what a package *is*). The project's shared
  *ubiquitous language* is the **Shared Kernel** (the value packages
  `money`/`ratio`/`quantity`/`unit_price`) + cross-cutting policy
  (`authority`/`coverage`/`config`/`observability`).
- **Package-level contract** — each package's `contract.py` (`interface == __all__`,
  invariants, `units`), which *conforms to* meta's project-level schema. `meta`
  self-hosts: it is a package whose package-level contract conforms to the schema it
  defines at the project level.

**One uniform package shape** (every package, no exceptions): a language-neutral
**contract** + one-or-more per-runtime **implementations**, each converging into
`base / extension / data` carrying `units` (`kind → layer`).

**Placement falls out of one rule:**
- the **contract** is language-neutral → `common/<pkg>/` (`contract.py`, `readme`,
  and when cross-runtime: `contract/<pkg>.contract.md` + `conformance/vectors.json`);
- each **implementation** lives where it runs → `apps/<runtime>/<pkg>/`, named by
  `implementations` (`be`/`fe`); a package may have one or two.

A package whose **strategic role is project-wide shared** — the **Shared Kernel**
(value language) and the **meta-model + policy** (`meta`/`authority`/`coverage`/
`config`/`observability`) — *is* shared code, so its implementation lives in
`common/`. That is what `common/` means; it is **not** a special "layout", just a
DDD package whose role is "shared by everyone". The two example shapes below are
illustrations of the one rule, not choices to pick.

### Example shape A — a domain / supporting package (counter, ledger, reporting, …)

Contract in `common/`, implementation in `apps/<runtime>/`. `data` is metadata in
`contract.py` until the package has real projection code.

```
common/<pkg>/                         spec + review surface
  __init__.py                         re-exports CONTRACT
  contract.py                         interface · units=[Unit(kind=…)] · invariants · roadmap(ACs)
  readme.md  todo.md                  prose (absorbs the package's SSOT) + worklist
apps/backend/src/<pkg>/               BE implementation  (implementations["be"])
  __init__.py                         __all__ == contract.interface
  base/        types/ ops/ ports      pure core — downward DAG, no I/O
  extension/   sql.py  api/           impure edges — ORM / transport / cross-package
apps/frontend/src/lib/<pkg>/          FE implementation (optional; implementations["fe"])
apps/backend/tests/<pkg>/             behavior tests
tests/tooling/test_<pkg>_package.py   contract / invariant tests
```

### Example shape B — a project-level shared package (Shared Kernel `money`/…; meta-model `meta`)

Its role is project-wide shared, so its **implementation lives in `common/`** (not a
special case — that is what `common/` is for). A cross-runtime Shared-Kernel value
additionally keeps BE/FE mirrors honest via `conformance/vectors.json`.

```
common/<pkg>/
  __init__.py  contract.py  readme.md  todo.md
  contract/<pkg>.contract.md          language-neutral interface spec (the cross-runtime contract)
  conformance/vectors.json            shared BE/FE parity vectors (the consistency guarantee)
  base/                               canonical pure value types + ops
  extension/                          wire/db serialization edges
apps/backend/src/<pkg>/               BE mirror — conforms to interface + vectors
apps/frontend/src/lib/<pkg>/          FE mirror — conforms to interface + vectors
```

`meta` (the meta-model package) is an instance of shape B — everything under
`common/meta/`; its `data/` is the computed index that replaces the hand-maintained
MANIFEST / registry:

```
common/meta/
  __init__.py  contract.py  readme.md  todo.md  migration-standard.md
  base/                               the model — PackageContract, tiers, proof matrix
  extension/                          the gate — check_package_contract (governs every package)
  data/                               the computed meta-index (registry · AC index · coverage)
```

### Deployment note (packaging, not a domain rule)

The backend image does not ship `common/`, so a Shared-Kernel value package
additionally keeps a self-contained **mirror** at `apps/backend/src/<pkg>` (and the
FE its own at `apps/frontend/src/lib/<pkg>`), kept honest by the conformance vectors.
That mirror is a **packaging artifact**, not a different kind of package — do not
mistake it for structure.

Live examples: `counter` (shape A) and `meta` (shape B). The gate
(`check_package_contract`) owns the `base↓ / extension↑` rule, the `kind → layer`
placement, the repository port/adapter split, and the data-sink rule — uniformly,
for every package.

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
