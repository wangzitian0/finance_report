# `reporting` — financial report generation over the ledger (domain package)

> Package model: [`../meta/readme.md`](../meta/readme.md). Machine contract:
> [`contract.py`](./contract.py).
>
> This `common/reporting/` directory is the **spec + review surface**; the
> conforming implementation still lives at
> `apps/backend/src/services/reporting` (`contract.implementations["be"]`) —
> unlike a fully carved package, it has not yet been physically relocated to
> `apps/backend/src/reporting/`.
>
> **Status: `active`, `tier="CODE-ONLY"`** (flipped in migration closeout
> wave 2, #1663 — see [Status](#status) below). Physical relocation out of
> `services/` is still pending; that doesn't block the AC/tier decision.

## Why

Balance sheet, income statement, cash flow, and net worth all read the same
posted ledger state through different lenses. `reporting` is the calculation
layer over `ledger` (and, via `pricing`, over valuation) that produces those
views — it never itself decides what a position is worth or whether a match
is reconciled; it consumes those facts.

## Scope correction (2026-07-06)

`manual_valuation.py` belongs to the `pricing` cutover (#1610), not here:
reporting keeps confidence-tier mapping and report assembly; `pricing` owns
valuation-observation staleness facts. This contract's
`manual-valuation-excluded-from-reporting-language` invariant pins that
boundary so it cannot silently drift back.

## Ubiquitous language

- **`ReportSnapshot`** — the aggregate root: a generated, framework-anchored
  report as of a period, holding its own provenance/confidence-tier lineage.
- **`generate_balance_sheet` / `generate_income_statement` / `generate_cash_flow`**
  — the three statement generators, each composing the shared aggregation
  core (`_aggregate_balances_sql`/`_aggregate_net_income_sql`).
- **`FrameworkPolicyMatrix` / `FrameworkPolicyDecision` / `FrameworkPolicyGap`**
  — the framework-anchoring language (which accounting framework a line maps
  to, and what's missing for a 1:1 mapping).
- **`get_net_worth_timeseries` / `get_net_worth_allocation_schedule` /
  `get_category_breakdown` / `get_account_trend`** — the net-worth reporting
  lane, separate from the three core statements.
- **`get_account_lineage`** — per-account provenance/traceability, not a
  statement itself.

## Cross-package edges

`ledger` (posted entries are the source of truth), `portfolio` (position
valuation feeds net worth), `pricing` (price/FX resolution — reporting never
looks up a rate itself), `extraction` (source-type confidence tiers feed
provenance), `reconciliation` (match state feeds readiness), `audit` (base
value types).

## Status

`status="active"`, `tier="CODE-ONLY"`, `roadmap` has 14 ACs: the opening-
balance confidence-tier gate (migrated from EPIC-002, which never owned this
behavior — it's report assembly, not double-entry posting), the full
EPIC-020 framework-aware personal reporting set, and the EPIC-025 DRY/SSOT
reporting-calculation-extraction pair (`dry-ssot.1`/`.2`) — all `proof_kind`
in `{exact, property}`, valid under `CODE-ONLY`. EPIC-005's larger AC set
still lands in a follow-up commit once the `services/` -> package-home move
is complete — the tier decision above doesn't depend on that landing first.
The physical move from `apps/backend/src/services/reporting/` into
`apps/backend/src/reporting/` is also still pending.
