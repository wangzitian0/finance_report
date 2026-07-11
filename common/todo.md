# `common/` — cross-package / migration worklist

The horizontal worklist for migrating to the target architecture in
[`meta/migration-standard.md`](./meta/migration-standard.md). Each package also
keeps its own `common/<pkg>/todo.md`; this file tracks the migration *between*
packages and the phase order. Umbrella issue: **#1416**.

## Target packages (live membership: `common/meta/base/layering.py::PACKAGE_LAYER`)

Two governors + the technical substrate + the shared valuation SSOT + the
financial flow (see the standard for each package's base/extension/data +
entities + governance domain):

- **meta** — governs *form* (structure/deps/acyclic/progress).
- **audit** — governs *number* (= the old `value` folded in: financial base types
  + `ExchangeRate` conversion *math* + accounting consistency + traceability).
- **platform** — event bus / outbox / workflow / pipeline / counter / identity
  (the substrate historically labelled *middleware*, #1427).
- **llm** — provider abstraction / cassette / stream.
- **pricing** — one price/valuation SSOT, orthogonal to the flow (#1610):
  unified `PriceObservation` + `PriceableSubject` + `resolve(subject, as_of,
  policy)`, replacing `FxRate` / `StockPrice` / `MarketDataOverride` /
  `ManualValuationSnapshot` and the `fx` / `market_data` / `assets` services.
  Sequenced before `portfolio`, which consumes it.
- financial flow: `(extraction [auto] + portfolio [manual]) → reconciliation → ledger → reporting → advisor`.

Internal layering is **base↓ / extension↑ / data** (replaces kernel/platform/core
and types/ops/store/api). ACs are `AC-<pkg>.<entity>.<seq>` in each contract's
`roadmap`. **The migration unit is the AC.**

## Phases (each package cutover = one atomic PR, by the standard's DoD)

| phase | scope | issue · status |
|-------|-------|----------------|
| 0a | standard doc + `governance→meta` rename | #1414 ✅ |
| 0b | `counter` → base/extension/data template + gate three-layer rule (additive) | #1418 ✅ |
| 1 | `value → audit` fold | #1419 ✅ |
| 2 | `ledger` | #1420 ✅ |
| 3 | `extraction` #1421 ✅ · `portfolio` #1422 ✅ · `reconciliation` #1423 ✅ · `reporting` #1424 ✅ · `pricing` contract ✅ `status="active"` (roadmap populated in the wave-2 closeout, #1663/#1728; #1610 stays open for the physical-table unification) | partial |
| 4 | `advisor` #1425 ✅ · `llm` #1426 ✅ · `platform` #1427 ✅ · `identity` #1428 ✅ | done |
| 5 | `audit` consistency closeout (global invariants + cross-package ACs) | #1429 ⬜ |
| 6 | cleanup — delete residual EPIC tables / SSOT; retire the central `docs/ssot/MANIFEST.yaml`/registry gates once meta's data layer is the computed index | tracked as a 3-wave closeout: #1662 (finish cutovers + doc-sync) → #1663 (EPIC AC migration) → #1664 (SSOT/index retirement); #1430 closed early on the directory-coverage-only reading |

All tracked under umbrella **#1416**. Every package listed above ships a
`contract.py` — "✅" here means the cutover PR merged, not that the roadmap or
readme is complete; see [`common/readme.md`](./readme.md#map) for each
package's live `status`.

## Definition of Done per package (from the standard)

A package cutover is one atomic PR that:
1. moves each AC to the package `roadmap` as `AC-<pkg>.<entity>.<seq>` (removed from the EPIC table);
2. deletes the EPIC only once **all** its ACs are distributed;
3. internalizes the package's owned SSOT (into readme/contract; removed from `docs/ssot/` + `docs/ssot/MANIFEST.yaml`);
4. migrates its tests (every `invariants[].test` / `roadmap[].test` resolves);
5. repoints consumers to the published `interface` (`__all__`), not submodules;
6. **removes the original** — pre-migration modules are deleted, not copied: no
   leftover code, re-export shim, test, or import of the old path remains
   (a lingering original means the package is NOT migrated);
7. is green (`check_package_contract` + the package's own invariants).

Different packages may be old-or-new during the migration; a single package is
never left half in both an EPIC and a roadmap.

## Conventions every migration must keep

- A package's ACs live in its `contract.py` `roadmap`, **never** mirrored into an
  EPIC table.
- `contract.interface` must equal the BE implementation's `__init__.__all__`;
  FE conforms to the same interface + conformance vectors (FE picks its own impl).
- `base` imports only `base` (downward DAG); `extension` is a separate import
  surface (no cycle); `data` is metadata only. Rule: *never up, never sideways-cyclic*.
- Adding a package adds no central index edit — shipping `common/<pkg>/contract.py`
  registers it with the governance gate.

## App-boundary burndown (the L4 `backend` super-package)

The un-carved remainder of `apps/backend/src` (`services/` / `routers/` /
`prompts/`) is the L4 `backend` super-package. `check_app_boundary` freezes its
coupling to the already-carved packages in `docs/ssot/app-boundary-baseline.json`
(monotonic: new edges fail CI). **This count is the migration burndown** — it
drops as each domain is carved out.

- The baseline count moves as domains are carved and more edges are discovered;
  read `docs/ssot/app-boundary-baseline.json` directly (or its generated
  summary) for the live edge count and per-package breakdown rather than
  copying a snapshot number here — it goes stale immediately.
- Outbound edges (a carved package → the app remainder, upward-layer) have
  historically concentrated in `extraction`. They reveal deps `extraction`
  never internalized: things like `ai_streaming` / `storage` / `pii_redaction`
  belong in lower packages (llm / runtime / audit); `chain_repair` /
  `assets` are domain logic. **Clear outbound before inbound** when carving a
  domain out. (`promotion_gate` cleared by #1667 — relocated into
  `audit.promotion`, consumed by `extraction`/`reconciliation`/`ledger`
  through the published interface instead of a `services.*` reach-through.)
- Target: baseline → 0 when `reconciliation` / `reporting` / `portfolio` /
  `advisor` / `asset` are carved and the remainder is empty.
