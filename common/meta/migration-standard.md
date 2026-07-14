# Package migration standard (the target architecture)

> The standard the whole repo migrates **to**: high-cohesion packages (live
> membership: `common/meta/base/layering.py::PACKAGE_LAYER` — the count lives in
> code, not in this prose), each
> code-owning its contract + docs, so EPIC tables and most SSOT prose are absorbed
> and the repo becomes contract-driven. Owned by the `meta` package (this file is
> its prose). The only authored horizontal docs that survive are `vision.md` and
> each package's `readme.md`.

## Why

We keep auditing **drift** between EPIC AC tables / central SSOT indexes and the
code, because central mirrors must be hand-synced and don't stay in sync. The fix
is to delete the mirror: **the contract is the single source**, governance is
**computed**, and meta-info is **aggregated**, never hand-maintained.

## The financial-domain core packages

Two cross-cutting governors (parallel peers, not super-packages) + the value
foundation + the shared valuation SSOT + the financial data flow + the technical
substrate. **This is the financial-domain core, not the whole registry**: more
packages exist alongside this core and are governed the same way —
`observability`/`runtime`/`testing` on the infra axis, `counter` in the
middleware kernel, `identity` as a domain slice outside the financial flow
(`config` folded into `runtime`, #1669); `PACKAGE_LAYER` is the authoritative
list. They're omitted from the table below because they carry no
financial-domain vocabulary of their own to describe, not because they're
second-class.
`common/meta/base/layering.py::PACKAGE_LAYER` is the actual current-membership
list (a hand-synced count here went stale twice — read the code, not a snapshot
of it); this table is target *design intent* for
the financial-domain packages specifically, and **the table's `extension deps`
column is not always what `depends_on` says today** — a package's `contract.py`
declares only edges with a real import behind them (`check_package_contract`
fails an unused declaration as of #1674), so a package earlier in its cutover
legitimately depends on less than this table describes until the rest of the
design lands (e.g. `portfolio`/`reconciliation` are write-side-only today; their
`pricing`/`platform` edges here are not yet real code). Treat this table as
*where a package's contract is heading*, and the contract + the gate as *what's
true right now*:

| package | base deps | extension deps | own info (base) | governance domain (extension) |
|---|---|---|---|---|
| **meta** | — | (reads every contract) | DDD domain/package structure, interfaces, tooling | every package is well-formed: structure / deps / acyclic / migration progress |
| **audit** | — | ledger, extraction, portfolio, reporting, pricing | financial base types (Money/Ratio/Quantity/UnitPrice + `convert(money, rate)` **conversion arithmetic**, rate passed as an argument — audit never looks up a rate) + invariants + confidence/provenance + trace records | global numeric correctness + accounting consistency + end-to-end traceability |
| **platform** | — | — | event bus / outbox / workflow / pipeline / counter / identity (the substrate historically labelled *middleware*, #1427) | how domain packages plug in: delivery atomicity, auth boundary |
| **llm** | — | platform | provider abstraction, cassette, stream | LLM calls are deterministically replayable; no secret in argv |
| **extraction** | audit | platform, llm | auto-extracted types (Statement/Transaction/Confidence/Dedup) | source→fact balance chain, dedup conservation |
| **portfolio** | audit | platform, pricing | investment positions (Position/InvestmentLot/InvestmentTransaction/Dividend/CostBasis) | position quantity ≥ 0, cost-basis consistency; consumes prices, does not own them |
| **pricing** | audit | platform | **the price/valuation observation + resolution SSOT** — `PriceObservation` (subject, as_of, observed_at, source, authority) is append-only; `PriceableSubject` unifies the currency-pair/security/component key vocabularies; `resolve(subject, as_of, policy)` is the domain service (not a lookup) | exactly one resolved value per (subject, as_of, policy); overrides never mutate/delete (Axiom A); bitemporal — a late backfill never changes what `resolve` returned at an earlier knowledge time |
| **reconciliation** | audit, extraction, portfolio | platform, ledger, pricing | matching/review (Match/Review/Correction/ProcessingAccount) | record↔evidence consistency, two-stage review, in-transit visibility |
| **ledger** | audit | reconciliation | double-entry (Account/JournalEntry/Line/Balance) | debits = credits (See: common/ledger/readme.md#entry-balance), only reconciled facts post |
| **reporting** | audit | ledger, portfolio, pricing | reports (ReportPackage/FrameworkPolicy/Snapshot/Readiness) | report lines reconcile, framework 1:1 |
| **advisor** | audit | platform, llm, reporting, portfolio, pricing | AI advisor (Session/Suggestion/AnnualizedIncome) | advice never becomes a ledger number unchecked |

**Financial data flow:** `(extraction [auto] + portfolio [manual]) → reconciliation → ledger → reporting → advisor`.
**Shared valuation:** `pricing` is orthogonal to the flow — a single observation+resolution SSOT the flow consumes (portfolio marks positions to market, reconciliation checks per-currency balances, reporting restates net worth). It replaces the pre-migration split across `FxRate` / `StockPrice` / `MarketDataOverride` / `ManualValuationSnapshot` and the `fx` / `market_data` / `assets` services — but statement-extracted unit prices stay in `extraction` (document-fact, provenance chain); extraction publishes a `PriceObserved` event and pricing ingests an id-referenced copy (no shared transaction, no FK).

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

### `data/` = the domain's product: the wide-table projection contract

The endgame for a domain's *queryable output* is its `data/`-layer projection —
typically one denormalized **wide table** per product (reporting's snapshot is
the archetype). The contract that keeps CQRS honest:

- **Derived, never authored.** Only projection builders write it — domain logic
  never writes the wide table directly (invariants live in the write model);
  it is rebuildable from the domain's facts/events at any time.
- **Event-fed.** Own-domain writes plus subscribed upstream domain events (via
  the platform outbox, at-least-once) are the only inputs; consumption is
  idempotent — upsert keyed by `(aggregate_id, version)`.
- **Late events are bitemporal**, pricing-style: a backfill never rewrites what
  was queryable at an earlier knowledge time (Axiom A).
- **Zero FK.** A projection carries ids + values denormalized as of event time,
  never constraints; cross-domain reads at query time consume the other
  domain's published wide table or interface — not runtime joins into its
  write model.
- **Provenance on every row** (Axiom B): the ids of the upstream facts each row
  was computed from, so source→record→ledger→report tracing survives
  denormalization.

The first live precedent is #1642's extraction→pricing `PriceObserved`
subscriber; later `data/` sinks copy its shape.

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
   package (readme/contract); `docs/ssot/` itself is retired (#1823) — the
   concept's `owner:` in `common/meta/data/MANIFEST.yaml` points at the
   package, never a central doc.
4. **Tests migrated** — tests live with the package; every `invariants[].test` /
   `roadmap[].test` resolves.
5. **Consumers repointed** — importers use the package's published `interface`
   (`__all__`), not its submodules/internals.
6. **Original removed** — the pre-migration modules / god-files are **deleted, not copied**: no leftover code, re-export shim, test, or import of the old path remains. The package is the **single home** (zero duplication). Enforced like `counter` (its package test asserts the retired modules are gone) + the no-old-path-import lint (#1461 generalized). **A lingering original means the package is NOT migrated.**
7. **Green** — `check_package_contract` + the package's own invariants pass.

Each package cutover is **one atomic PR** (never leave a single package half in
both an EPIC and a roadmap). Different packages may be old-or-new during the
overall migration; a single package is never half-migrated — and "migrated" means
the old code is gone, not merely that a new copy exists.

A cutover that spans more than one domain still obeys **one transaction per
domain**: each domain's interface/event change lands as its own atomic step, never
a single edit reaching across domain boundaries. The enforcement is owned by the
cross-domain gate (issue #1460); this standard only states the rule.

## Anti-mud-ball guard

The win is real only if `base` layers stay clean and `extension` layers stay
**thin**. `meta`'s data layer tracks each package's **extension fan-out**
(cross-package edge count) as a metric, so coupling that creeps back into a fat
extension is visible, not hidden.

### The L4 `backend` super-package + the app-boundary ratchet

During the migration most of the flow is still un-carved: the remainder of
`apps/backend/src` (`services/` / `routers/` / `schemas/` / the composition
root) is, conceptually, the **L4 `backend` app super-package** — one holding
pen that shrinks as each domain is carved out. It is not yet a discovered package (its multi-subdir remainder
shape does not fit the "one package = one `src/<name>`" assumption of
`check_package_contract`), so that gate's deep-import rule is **blind** to the
coupling between the remainder and the already-carved packages.

`check_app_boundary` (`common/meta/extension/check_app_boundary.py`) closes that
blind spot, fail-closed, on a **monotonic baseline**
(`common/meta/data/app-boundary-baseline.json`) of two edge kinds:

- **inbound** — the remainder importing a carved package's *unpublished internal*
  (an encapsulation leak: a "completed" package silently losing its boundary);
- **outbound** — a carved package importing the app remainder (an L1/L3 → L4
  **upward-layer** edge — the chain that stops a carved package from being
  liftable; clear these *first* when carving a domain out).

The baseline may only **shrink**: a new edge in either direction fails CI. Its
size is the real migration burndown — carving a domain out of the super-package
removes its edges from the baseline, driving it toward zero.

> The standalone `check_app_boundary` gate is the accepted end-state: with the
> app delivery layer sanctioned below (#1763), no remainder-aware `backend`
> contract or fold-in to the core deep-import scan is planned.

### The app delivery layer (the sanctioned L4 remainder)

Not all of the L4 remainder is a holding pen. The physical remainder today is
`routers/` + `schemas/` + the composition root (sanctioned, below). The
formerly-unsanctioned holding pens are now fully dissolved: `services/` (its
last tracked file, an empty `__init__.py`, was deleted by the #1429/#1677
closeout) and `prompts/` (dissolved into its owning packages per the
`prompts/` bullet below) — neither has any tracked file left under
`apps/backend/src`. `routers/` (HTTP delivery
adapters), `schemas/` (API DTOs), and the composition root (`main.py` /
`boot.py` / `deps.py` / `config.py` / `config_app.py` / `database.py`) are the
**sanctioned app delivery layer** (#1763 ruling): hexagonal **primary
adapters** of the application, not domain behavior. A bounded context does not
need to own its HTTP surface — dissolving the routers pile into every package
would hand each one a FastAPI dependency and a route-registration protocol,
more coupling than it removes; the composition root is likewise standard. What
keeps the sanction honest:

- **Published roots only** — routers/schemas import carved packages only via
  their published interface (#1739 drove the inbound edges 43→1; the
  app-boundary ratchet above holds it).
- **Thin-ness ratchet** — routers hold no domain logic, approximated as a
  shrink-only line-count baseline for `routers/` + `schemas/`
  (`common/meta/data/delivery-layer-baseline.json`, gate
  `tests/tooling/test_delivery_layer_ratchet.py`, AC-meta.delivery.1): the
  census must stay within a 50-line band of the baseline — silent growth fails
  CI; growing the delivery layer requires raising the baseline in the same PR,
  where the diff makes the choice reviewable (the app-boundary idiom);
  meaningful shrink lowers the baseline in the same PR so the ratchet stays
  tight. `schemas/` entries retire opportunistically as packages publish their
  own interface types — shrink-only, no dedicated campaign.
- **`prompts/` is NOT sanctioned** — prompt text is domain content, not
  delivery; it dissolves into its owning packages (the reconciliation prompt
  lives at `src/reconciliation/base/prompts.py` since PR #1748; the advisor
  prompt moves with #1671 Wave B).

## Cross-domain reference policy (FK / relationship / cascade)

How one domain's tables may refer to another's (#1675 ruling, 2026-07-11;
enforced by `check_package_contract` (AC-meta.txn.3) and the cascade ratchet
(AC-meta.txn.4)):

1. **Intra-domain FK — free.** Constraints between tables of one bounded
   context (ledger's journal↔accounts↔lines) are domain-internal integrity,
   invisible to this policy.
2. **Cross-domain bare `ForeignKey` column — allowed; cross-domain
   `relationship()` — banned.** In this modular monolith (one process, one
   database, one transaction manager) a bare FK column is a DB-level
   referential-integrity invariant, not code-level coupling; the real coupling
   is object-graph navigation, which the gate rejects. In code, aggregates
   still reference each other **by id** and resolve through the published
   interface or an event (mechanism C). `FK(users.id)` — the `UserOwnedMixin`
   **tenancy anchor** on nearly every table — is the named degenerate case:
   the tenancy axis is orthogonal to the business flow and never a flow edge.
3. **`ondelete="CASCADE"` — ratcheted.** A DB cascade is a hidden write below
   the application: one table's delete silently mutates other rows. Across
   domains that breaks one-txn-per-domain (Decision B) and append-only domains
   (Axiom A) — the case this policy exists for. The census in
   `common/meta/data/fk-cascade-baseline.json` covers **every** CASCADE site,
   deliberately not domain-aware (table→package ownership only becomes
   trivially derivable after models decentralization, #1675 D5/D6); what CI
   enforces is census == baseline — silent growth fails, adding a cascade
   requires raising the baseline in the same PR so the diff makes the choice
   reviewable (the app-boundary idiom), removals prune it in the same PR.
   Existing sites are grandfathered; the end-state is **saga-owned deletion**
   (identity publishes a purge event; each domain deletes by its own
   semantics — `identity/extension/account_purge.py` is the seed). Whether
   grandfathered cascades then flip to `RESTRICT` is a separate, later
   decision (#1675 D7), never bundled into a move.

## Migration order

1. **Step 0** — this standard (0a) + refactor `counter` into base/extension/data
   as the worked template, and extend `check_package_contract` to support the
   three-layer rule (additive; existing packages keep working). (0b)
2. **value → audit** fold (its own PR).
3. **ledger** (the prototype domain-layer cutover, already has a legacy `.contract.md`).
4. **extraction / pricing / portfolio / reconciliation / reporting** (the flow; pricing before portfolio, which now consumes it).
5. **advisor / llm / platform / identity**.
6. **audit** consistency closeout (global invariants + cross-package ACs).
7. **Cleanup** — delete residual EPIC tables / SSOT, retire the central
   MANIFEST/registry gates once `meta`'s data layer is the computed index.

## Related

- [`readme.md`](./readme.md) — what a package is (the model).
- [`contract.py`](./contract.py) — the `meta` package's own contract.
- [`../../vision.md`](../../vision.md) — the only authored north-star.
