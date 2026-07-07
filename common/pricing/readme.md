# `pricing` — the price/valuation observation + resolution SSOT (domain package)

> Package model: [`../meta/readme.md`](../meta/readme.md). Machine contract:
> [`contract.py`](./contract.py).
>
> This `common/pricing/` directory is the **spec + review surface**; the
> conforming implementation lives at
> [`apps/backend/src/pricing`](../../apps/backend/src/pricing)
> (`contract.implementations["be"]`).
>
> **Status: `draft`** (design review #1610 landed the model + resolver +
> repository + FX wrappers; the roadmap is still empty pending the
> EPIC-011/005/017 pricing-AC migration — see [Status](#status) below).

## Why

Pre-migration, "what is X worth at time T" was scattered across 5 tables with
3 incompatible key vocabularies (`FxRate`, `StockPrice`, `MarketDataOverride`,
`ManualValuationSnapshot`, plus statement-extracted unit prices), and the
resolution logic (which observation wins when several disagree) was implicit
and re-derived at each consumption site. `pricing` unifies this into one
observation + resolution SSOT, orthogonal to the financial flow: portfolio
marks positions to market, reconciliation checks per-currency balances,
reporting restates net worth — all through the same `resolve(subject, as_of,
policy)` call.

## Ubiquitous language

- **`PriceObservation`** — the aggregate root: a subject was worth X at time
  T, from a source, with an authority rank. Append-only (Axiom A) — an
  override is a new higher-authority observation, never a mutation; deleting
  one re-exposes the prior observation.
- **`PriceableSubject`** — unifies the 3 legacy key vocabularies (currency
  pair / listed security / valued component) into one subject identity.
- **`resolve(subject, as_of, policy)`** — the domain service, not a lookup:
  consumers pass a `ResolutionPolicy` (reporting wants conservative, portfolio
  wants latest).
- **Bitemporal** — `as_of` (which day the price belongs to) ≠ `observed_at`
  (when we learned it). A late backfill must never silently rewrite a frozen
  `ReportSnapshot`.
- **`PriceObserved`** — the domain event `pricing` publishes (through the
  platform outbox, atomically with the write) whenever a new observation is
  recorded; `extraction` is one producer (`source=statement`), the manual
  recorders another (`source=manual-override`).

## Boundary rulings (record, don't relitigate — see #1610)

1. Statement-extracted unit prices stay in `extraction` (document-fact,
   provenance chain, re-parse lifecycle); `extraction` publishes `PriceObserved`
   and pricing ingests an id-referenced copy. No shared transaction, no FK.
2. FX splits in two: conversion *arithmetic* (`audit.money.convert(money,
   rate)`, rate passed in, pure) stays in `audit` — audit never looks up a
   rate; rate *lookup* + FX-specific services (inverse, triangulation, gap
   interpolation) live here.
3. Staleness is a fact pricing owns; the tier mapping ("too stale for this
   report") is policy the consumer owns.

`pricing` is an L3 domain leaf: it imports no other L3 (domain) package —
portfolio/reporting/reconciliation declare the (acyclic, sideways) edge TO
pricing, never the reverse.

## What's real today

The pure `base/` model (`PriceObservation`/`PriceableSubject`/
`ResolutionPolicy`), `resolve()`, the `ObservationRepository` port + its
read-only SQL adapter (querying the 4 legacy tables directly — schema-preserving
on purpose, so this lands ahead of a unified physical store), the two
user-scoped write-side recorders (`record_manual_valuation`/`record_override`,
each publishing `PriceObserved` atomically with the write), and the FX lookup +
`convert_*` + average-rate wrappers (`extension/fx.py`).

Reserved (declared in [`contract.py`](./contract.py), no `module=` yet): the
crawler sync (`sync_market_data`) and the extraction-event subscriber
(`ingest_statement_price`), plus the `LatestPriceView`/`StalenessView` read
projections.

## Status

`status="draft"`, `tier=None`, `roadmap=[]` — the write/read surface above is
implemented and tested, but the package doesn't yet carry its own ACs: they
remain in `docs/project/EPIC-011.asset-lifecycle.md` /
`EPIC-005.reporting-visualization.md` / `EPIC-017.portfolio-management.md`
pending the mass AC migration (tracked in the migration closeout series,
umbrella #1416). Remaining consumer wiring is tracked in #1610 PR2. The
package goes `status="active"` once its roadmap is populated and an authority
tier is decided.
