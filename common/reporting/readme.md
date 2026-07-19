# `reporting` — financial report generation over the ledger (domain package)

> Package model: [`../meta/readme.md`](../meta/readme.md). Machine contract:
> [`contract.py`](./contract.py).
>
> This `common/reporting/` directory is the **spec + review surface**; the
> conforming implementation lives at `apps/backend/src/reporting/`
> (`contract.implementations["be"]`), physically folded out of `services/`
> by #1666:
>
> - `base/` — the pure core: framework/line vocabulary (`types.py`), the L1
>   report-line registry (`l1_registry.py`),
>   and the static package contract/notes/traceability data
>   (`report_package_contract.py`).
> - `extension/` — statement generation (`_core.py`, `balance_sheet.py`,
>   `income_statement.py`, `cash_flow.py`, `net_worth.py`, `lineage.py`,
>   `internal_transfer.py`, `portfolio_market.py`), framework assembly
>   (`framework_policy.py`, `framework_report.py`), the package lane
>   (`report_readiness.py`, `report_traceability.py`, `report_package.py`,
>   `reporting_snapshot.py`), the calculation primitives
>   (`reporting_calc.py`), confidence (`confidence_tier.py`,
>   `confidence_metric.py`), and the injected FX seam (`fx_gateway.py`).
> - `data/` — reserved for the declared projections (no module yet).
>
> Reporting keeps zero FX logic and zero manual-valuation logic of its own —
> both arrive by composition-root injection (`register_fx_gateway` /
> `register_manual_valuation_lines_provider`, wired in `main.py` and the
> backend test conftest) rather than a direct import, so a rename inside the
> owning package never touches reporting's consumer modules. Both ports now
> repoint to `pricing` (#1610 retired the `services/fx.py` /
> `services/reporting/manual_valuation.py` implementations they originally
> pointed at).
>
> **Status: `active`, `tier="CODE-ONLY"`** (flipped in migration closeout
> wave 2, #1663 — see [Status](#status) below).

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
Pricing also owns manual-valuation line naming. Reporting consumes the produced
lines and the ledger-owned `worst_confidence_tier`; it defines neither helper.

## Ubiquitous language

- **`ReportSnapshot`** — the aggregate root: a generated, framework-anchored
  report as of a period, holding its own provenance/confidence-tier lineage.
- **`generate_balance_sheet` / `generate_income_statement` / `generate_cash_flow`**
  — the three statement generators, each composing the shared aggregation
  core (`_aggregate_balances_sql`/`_aggregate_net_income_sql`).
- **`FrameworkPolicyMatrix` / `FrameworkPolicyDecision` / `FrameworkPolicyGap`**
  — the framework-anchoring language (which accounting framework a line maps
  to, and what's missing for a 1:1 mapping).
- **`PersonalReportingFrameworkId` / `ReportLineId` / `PolicyDimension`** —
  reporting-owned base vocabulary. `src.schemas.reporting` re-exports these
  exact definitions for delivery compatibility and never defines a second copy.
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

`status="active"`, `tier="CODE-ONLY"`. The roadmap's first wave: the opening-
balance confidence-tier gate (migrated from EPIC-002, which never owned this
behavior — it's report assembly, not double-entry posting), the full
EPIC-020 framework-aware personal reporting set, and the EPIC-025 DRY/SSOT
reporting-calculation-extraction pair (`dry-ssot.1`/`.2`) — all `proof_kind`
in `{exact, property}`, valid under `CODE-ONLY` (the roadmap has since
absorbed the EPIC-005/EPIC-008 reporting rows, #1716). The physical move from
`apps/backend/src/services/reporting/` into `apps/backend/src/reporting/`
landed with #1666; `services/reporting/manual_valuation.py` was the sole
survivor and #1610 re-homed it into `pricing/extension/valuation.py`,
deleting the directory.

## SSOT: report calculation rules

*(Internalized from `common/reporting/reporting.md`, migration closeout wave 3,
#1664 — this is now the single owner; do not re-add a separate SSOT copy.)*

### Automated report preparation contract

Reports are prepared from trusted ledger facts, reviewed records, owned
valuation snapshots, and market data with explicit source basis. Once the
user has uploaded supported source documents, report preparation assembles
the required sections automatically wherever deterministic rules and
registered ACs exist — multi-currency conversion, investment valuation,
annualized income, ESOP/RSU and other long-term compensation schedules,
fixed recurring expense accrual/pre-deduction presentation, report-readiness
blockers, notes, and source links. If an input is missing, stale, ambiguous,
or outside the implemented contract, the report discloses the limitation or
blocks readiness instead of silently filling the gap.

The Upload surface may consume the required source classes from the source
coverage matrix as a user-facing checklist before statement upload; the
frontend does not own source-trust classification — package readiness and
source-trust endpoints remain authoritative for whether a source class is a
gap, manual-trusted, imported/supported, or ready for trusted report output.
Manual evidence classes (ESOP/RSU plans, property statements, liability
statements, manual records) must stay visibly manual-trusted; the Upload UI
must not imply they are automatically imported or parsed.

### Report snapshot determinism

`report_snapshots` stores generated ADS report payloads. Regeneration may
keep historical non-latest rows for the same report date, but the database
prevents conflicting published state: point-in-time reports have at most
one `is_latest=true` row per `(user_id, report_type, as_of_date)`; range
reports have at most one per `(user_id, report_type, start_date,
as_of_date)`; range snapshots require `start_date <= as_of_date`.

Personal report package snapshots use the same Layer 4 table with
`report_type = package`. They freeze the package artifact rather than a
classification-rule version, so `rule_version_id` may be null for package
rows. Generation stores the package period, currency, selected framework,
readiness state, source-trust summary, framework policy result,
traceability appendix, and section payloads in `report_data`.

Package snapshot endpoints:

- `POST /api/reports/package/generate` creates a saved package snapshot for
  the requested `framework_id`, `start_date`, `end_date`, `as_of_date`, and
  `currency`.
- `GET /api/reports/package/snapshots` lists the current user's saved
  package snapshots.
- `GET /api/reports/package/snapshots/{snapshot_id}` reopens the saved
  payload without recalculating live report data.
- `GET /api/reports/package/snapshots/{snapshot_id}/export?format=json|csv`
  exports the saved snapshot; JSON and CSV export must be derived from
  `report_data`, not from live report endpoint recalculation.

The export endpoints (`GET /api/reports/export` and the snapshot export
above) return a bare `StreamingResponse`, so their media type and
attachment header are declared by the typed contract `ExportStreamEnvelope`
(`apps/backend/src/schemas/streaming.py`), constraining media type to
`text/csv`/`application/json` and rendering `Content-Disposition:
attachment; filename=...` from a validated filename.

Readiness gates the generated artifact status: if readiness is `ready`,
`generated`, or `stale` with zero blockers, the snapshot is `trusted`;
blocked, processing, or draft readiness can only create a `draft` snapshot.
Draft snapshots are still immutable and exportable, but consumers must not
describe them as trusted output.

### Report types

**Balance sheet** (assets/liabilities/equity at a point in time):
`Total Assets = Total Liabilities + Total Equity + Net Income + Unrealized
FX Gain/Loss + Net Worth Adjustment Gain/Loss`.

**Opening balances** (year-start positions, [#949](https://github.com/wangzitian0/finance_report/issues/949),
`AC-ledger.15.*`) — a balance sheet built only from imported statement
activity is incomplete for a user who starts tracking mid-life. The guided
opening-balance flow establishes starting positions so the as-of balance
sheet isn't silently understated:

- **One balanced entry** — `POST /api/accounts/opening-balances` posts a
  single journal entry increasing each supplied account to its opening
  balance on its normal side; the net offsets into a system Opening Balance
  Equity account so the entry balances and the accounting equation holds.
  Opening Balance Equity surfaces inside the balance sheet's `EQUITY`
  section, not as an asset or liability.
- **A starting position, not a delta** — rejected when an affected account
  already has posted activity before the opening date, so the posted
  amount can never stack on top of an existing balance.
- **Base currency only** — accepted only in the report base currency, with
  a clear error instead of a confusing downstream FX-rate failure; an
  account whose currency differs from the request is rejected.
- **User-managed accounts only** — even though SYSTEM-typed (it touches the
  system equity account), the request may only target user-managed
  accounts; a system account such as Processing cannot be seeded this way.

Because opening balances are ordinary posted journal entries, every
downstream report (net-worth time-series, cash-flow opening position) reads
them through the same ledger path — there is no separate "opening balance"
report code path. Posting mechanics (account resolution, equity offset) are
owned by [`common/ledger/readme.md`](../ledger/readme.md); this doc owns
only how the resulting positions present in the balance sheet.

**Income statement** (income/expenses over a period) and **cash flow
statement** — cash-flow balances and activities use two different
accounting views: `beginning_cash`/`ending_cash` are cumulative signed
balances of cash/bank asset accounts before/through the period bounds;
`net_cash_flow = ending_cash - beginning_cash`; operating/investing/
financing activity rows are period movements only (inflows positive,
outflows negative), and activity totals sum signed row amounts, never
absolute values. Classification: operating = income/expense accounts,
investing = non-cash asset accounts, financing = liability/equity accounts;
cash/bank asset accounts fund beginning/ending cash and are not repeated as
activity rows.

**Net worth time-series** — `GET /reports/net-worth/timeseries?from=...&to=...&granularity=daily|monthly`
returns `{date, total_assets, total_liabilities, net_worth, currency}`
points; `daily` is capped at 366 points, `monthly` uses the period end
date, and each point reuses balance-sheet FX conversion as of that point's
date.

**Net worth allocation schedule** — `GET /reports/net-worth/allocation?as_of_date=...&currency=...&include_restricted=...`
is report-owned (not portfolio-owned) because it must reconcile ledger
accounts, active portfolio market-value adjustments, manual valuation
snapshots, and liabilities to the same net worth total as the balance
sheet. `value` is signed in the report currency (assets positive,
liabilities negative; the sum of all rows equals `net_worth`);
`percentage_of_net_worth = value / net_worth * 100` (2dp, `null` when net
worth is zero); rows group by `asset_class × liquidity_class ×
source_currency` and retain drill-through `source_lines`. Portfolio
ledger-backed cost basis groups with `public_equity`; broker account
residual value after cost-basis split remains `cash`. Manual valuation
component types map: property/mortgage → `real_estate`; CPF/provident
fund/retirement/social-security/long-term-benefit/legacy-savings/insurance-
cash-value → `retirement_and_benefit_assets`; ESOP/RSU/stock options →
`restricted_comp`; tax refunds → `cash`; tax payable/generic liabilities →
`liability`; other → `other`. The portfolio performance schedule remains
the source for period return, unrealized market-value gain/loss, price
freshness, and portfolio-only performance detail.

**Investment performance schedule** (EPIC-017-owned, consumed by this
package as the `investment_performance` report section) is the report-ready
portfolio input for the personal financial-report package.

The **asset-dashboard performance answer** is unrealized market-value
gain/loss, a simple return on cost basis valued at the schedule as-of date,
and a price-freshness flag, all derived from this schedule. `xirr`,
`time_weighted_return`, and `money_weighted_return` are analytical
reporting measures only; surfaces must not present them as the
asset-dashboard answer (robo-advisor non-goal).

Endpoint:
`GET /api/portfolio/performance/report-schedule?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD&as_of_date=YYYY-MM-DD&currency=SGD`

If dates are omitted, the schedule defaults to year-to-date: `period_end`
defaults to today, `period_start` defaults to January 1 of the period-end
year, and `as_of_date` defaults to `period_end`.

Response object:

| Field | Rule |
|---|---|
| `period_start`, `period_end`, `as_of_date`, `currency` | Echo the requested reporting period, valuation date, and presentation currency |
| `xirr`, `time_weighted_return`, `money_weighted_return` | Decimal-safe percentage metrics; return `null` with a note when input data is insufficient |
| `realized_pnl`, `unrealized_pnl`, `dividend_income`, `dividend_yield` | Decimal-safe schedule totals in `currency` |
| `holdings` | Per holding rows with quantity, cost basis, market value, realized/unrealized P&L, dividend income, and source currency |
| `allocation` | Sector, geography, and asset-class allocation rows whose percentages reconcile to the schedule market value |
| `data_freshness` | Latest price date, market-data provider, stale flag, `stale_holdings` per-holding stale list, and manual override basis |
| `source_links` | Brokerage statement/import IDs, price source IDs, ledger entry IDs, and report anchors needed for source-to-ledger-to-report traceability |
| `notes` | Methods and limitations for cost basis, price freshness, dividends, XIRR/TWR/MWR, and any manual overrides |

The schedule must not mutate ledger state. It assembles existing portfolio,
market-data, dividend, and journal-entry facts into a reporting payload
that can be exported or embedded by this package.

If no holding snapshot exists on or before `as_of_date`, the schedule may
use active current holdings only when the same asset has a manual
market-data override dated after `as_of_date`. The response must disclose
that report-preparation evidence in `notes`, expose the override in
`data_freshness.manual_override_basis`, and include a
`market_data_override` source link. This fallback is report-only evidence
and must not mutate ledger state or weaken historical portfolio holding
queries.

All monetary schedule fields are presented in the requested schedule
currency. Realized P&L uses the investment transaction date, dividend
income uses the payment date, current market value uses the schedule
`as_of_date`, and holding cost basis uses the managed position acquisition
date. Mixed-currency schedule amounts must not be added at raw nominal
amounts.

**Annualized income dashboard summary** —
`GET /api/income/annualized` uses the same trailing 365-day window as the
package schedule, returning salary/bonus/dividend/total income + currency +
as-of date; mixed-currency lines convert to the dashboard currency using
the trailing-period average FX rate before bucket/total aggregation.

**Account lineage drill-down** (EPIC-022) —
`GET /api/reports/account-lineage?account_id=...&as_of_date=...&start_date=...&currency=...`
returns the individual posted/reconciled journal lines behind one account's
report balance, applying the same status/date filters as the aggregated
reports and the same signed accounting rules (ASSET/EXPENSE debit
positive; LIABILITY/EQUITY/INCOME credit positive). Each line exposes a
`journal_line` identifier for `GET /api/evidence/lineage`; it is
report-only and never mutates ledger state. Accounts the user does not own
return `404`.

**Report line provenance** — Balance Sheet / Income Statement `ReportLine`
responses expose an optional `provenance` enum: `imported` (fully backed by
imported/confirmed statement entries), `manual` (fully backed by
user-entered facts, including manual valuation synthetic lines), `derived`
(system-derived/market-FX-adjusted/mixed provenance), or `null` (source
basis not safely derivable). For ledger account aggregates, provenance
combines contributing posted/reconciled `JournalEntry.source_type` values —
a single known class stays that class, mixed known classes collapse to
`derived`, unknown-only inputs stay `null`. Portfolio market valuation
adjustment lines are `derived`; manual valuation snapshot synthetic lines
are `manual`.

### Personal financial-report package contract

[#570](https://github.com/wangzitian0/finance_report/issues/570) owns the
stable package-level API/export contract defining how report sections plug
into one personal financial-report package, without duplicating the
calculation ownership of the supporting EPICs.

`GET /api/reports/package/contract` returns `package_id`
(`personal-financial-report-package`), `version` (`1.0`),
`period_semantics`, `supported_frameworks`, `selected_framework_id`,
`framework_policy_endpoint`, stable ordered `sections`, and
`export_contract`. Required sections:

| Section ID | Owner | Source endpoint | Status |
|---|---|---|---|
| `balance_sheet` | EPIC-005 | `/api/reports/balance-sheet` | ready |
| `income_statement` | EPIC-005 | `/api/reports/income-statement` | ready |
| `cash_flow` | EPIC-005 | `/api/reports/cash-flow` | ready |
| `investment_performance` | EPIC-017 | `/api/portfolio/performance/report-schedule` | ready |
| `annualized_income_long_term` | EPIC-011 | `/api/reports/package/annualized-income-schedule` | ready |
| `notes` | EPIC-005 | `/api/reports/package/notes` | ready |
| `traceability_appendix` | EPIC-018 | `/api/reports/package/traceability` | ready |

The frontend package-assembly route presents the package as a readable
deliverable (cover sheet + table of contents), requires a framework
selection before loading framework-scoped output, and reserves the package
layout with skeleton placeholders while loading. Two presentation layers:
the default reader layer uses plain-language labels; explicit audit-details
disclosures retain raw source-trust classes, blocker codes, framework
policy result IDs, matrix versions, line IDs, confidence tiers, review
states, and export column metadata. This is a presentation boundary only —
the frontend must not drop or recompute the policy/source-trust/readiness/
traceability/export facts.

**Package readiness** — `GET /api/reports/package/readiness` (owner:
EPIC-019 Slice 5, #639) is the package-owned readiness fact source; other
APIs may aggregate it but must not duplicate its derivation. `/reports` may
summarize `state`/`blocking_count`/`blockers`/
`source_trust_summary.gap_source_classes` for a trust-first landing cockpit,
but must not reimplement readiness/source-trust/blocker derivation in
frontend code.

Response contract: `package_id`; `state` ∈ `{draft, processing, blocked,
ready, generated, stale}`; `selected_framework_id`,
`framework_policy_inputs` (accounts/positions/manual valuations/dividends;
excludes bank statements/journal entries that don't produce EPIC-020 policy
facts), `framework_policy_decisions`, `framework_policy_gaps` in
`source_summary`; `label`/`action_href` (internal relative routes only);
`blocking_count`; ordered `blockers` (`code`, `label`, `severity`, `count`,
`reason`, `action_href`); `source_summary`; `generated_at`/`stale_since`
(ISO 8601). Duplicate canonical Processing system accounts (`code = 1199`)
are data corruption and must fail readiness derivation rather than select
an arbitrary balance.

State priority: `draft` (no report-supporting inputs) → `processing`
(statements uploaded/parsing, no blockers) → `blocked` (blockers exist) →
`stale` (latest snapshot exists but sources changed since) → `generated`
(latest snapshot exists, not stale) → `ready` (inputs exist, no blockers,
no snapshot generated yet).

Required blocker codes: `failed_parsing`, `pending_review`,
`balance_mismatch`, `reconciliation_blocked`, `consistency_check_blocked`,
`processing_account_unresolved` (Processing account doesn't net to zero
after base-currency conversion), `missing_source_coverage`,
`unknown_source_anchor` (a posted/reconciled entry's `source_id` doesn't
resolve to a typed source record), `unsupported_framework`,
`missing_framework_policy_result`, `unsupported_policy_domain`,
`framework_policy_missing_dimensions`, `framework_ai_suggestion_unreviewed`,
`missing_valuation_basis`, `stale_market_data` (listed
security/ETF/mutual-fund/bond positions lacking synced or manual-override
prices within 90 days). Readiness derivation is read-only — opening the
reports page must never create Processing accounts or other artifacts.
Framework-policy blocker `action_href` values point at `/reports/package`.

**Framework policy result** — `GET /api/reports/package/framework-policy`
(owner: EPIC-020 for policy decisions, EPIC-005 consumes for assembly).
Inputs `framework_id` (default `personal_us_gaap_like`), `start_date`,
`end_date`, `as_of_date` (period defaults to a trailing 365-day window).
Returns a read-only `FrameworkPolicyResult` (`result_id` fingerprints
framework, matrix version, period, decision + gap content) derived from
accounts, atomic positions, manual valuations, dividends, synced
`StockPrice`, and manual `MarketDataOverride` rows (pre-migration models;
both consolidate into `pricing`'s unified observation model, #1610) — it
must not mutate source records, journal entries, portfolio lots, market
data, or report snapshots. Package assembly must consume this result and
must not infer framework-specific lines directly from raw portfolio market
value. `/reports/package` requires a framework selection
(`personal_us_gaap_like` or `personal_hkfrs_like`) before loading
readiness/policy/section/export data, and passes the selected
`framework_id` explicitly rather than relying on the backend default.

**Annualized income and long-term compensation schedule** —
`GET /api/reports/package/annualized-income-schedule`: trailing 365 days
ending at `as_of_date` (defaults to request date); income basis is
`POSTED`/`RECONCILED` lines bucketed into salary/bonus/dividend/total by
account name, converted to the schedule currency before aggregation (never
added at raw nominal amounts; non-reporting-currency income uses the
trailing-period average FX rate); restricted compensation basis is the
latest as-of manual valuation snapshots for `esop`/`rsu`/`stock_options`
with `liquidity_class=restricted`. Liquid net worth excludes restricted
holdings by default (`/reports/balance-sheet` and the Balance Sheet page
both default `include_restricted=false`). Decimal fields serialize as
strings; restricted fair-value totals use the as-of FX rate while
per-holding source currency stays visible.

**Notes and disclosures** — `GET /api/reports/package/notes` (status
`ready`). Required note IDs: `basis-of-preparation`,
`reporting-period-and-currency`, `valuation-basis`,
`investment-market-data`, `source-confidence-review`,
`restricted-asset-treatment`. Each note carries an owning EPIC, method
basis, source state, applicable sections, and disclosure text. The
package-level non-compliance statement must say the report is not a
regulated filing, not an audit opinion, not legal advice, and not tax
advice — standards-inspired references are coverage/disclosure discipline
only, never implying regulated filing compliance.

| Note ID | Owner | Source state |
|---|---|---|
| `basis-of-preparation` | EPIC-005 | `package_contract` |
| `reporting-period-and-currency` | EPIC-005 | `request_parameters` |
| `valuation-basis` | EPIC-011 | `manual_valuation_snapshots` |
| `investment-market-data` | EPIC-017 | `brokerage_imports_and_market_data` |
| `source-confidence-review` | EPIC-018 | `reviewed_journal_and_statement_links` |
| `restricted-asset-treatment` | EPIC-011 | `manual_valuation_snapshots` |

**Traceability appendix** — `GET /api/reports/package/traceability`
(status `ready`) is a pure projection of the exact
`PackageSectionContribution` collection used to build the document manifest.
Each line maps one section/line to source and ledger anchors: `line_id`,
`section_id`, `label`, optional `amount_field`/`currency_field`,
`source_state`, `source_anchor` (`state` ∈ `{available, unavailable,
not_applicable}` + identifiers), and `ledger_anchor` (same shape). Details
carry the contribution input reference, amount/currency when present,
current decision id, review state, and reason code.

Reporting never follows a foreign ORM relation or guesses a source class from
`JournalEntry.source_id`. Extraction publishes current immutable statement
results, ledger publishes decision-anchored journal lines, and pricing
publishes resolved valuation observations including component, liquidity, and
valuation-basis metadata. An unproven contribution stays visible and blocks
the package through the manifest fold. A populated investment schedule without
an authoritative investment contribution is also blocked rather than silently
packaged. Non-ledger disclosures (for example, the non-compliance statement)
use `ledger_anchor.state=not_applicable`.

Completeness warning taxonomy: `missing_source_anchor` (trusted totals
aren't auditable until a source contribution or explicit manual input exists),
`manual_only_source` (manual rows need visible valuation observation +
basis), `stale_market_data` (investment values need freshness disclosure or
refreshed provider data), `duplicate_source_coverage` (must be excluded or
reviewed before trust), and `overlapping_statement_period` (needs review
before period totals are trusted).

**Export contract** — formats `json`/`csv`; CSV columns `package_id`,
`section_id`, `line_id`, `label`, `amount`, `currency`, `source_state`,
`selected_framework_id`, `framework_policy_result_id`,
`framework_policy_matrix_version`, `evidence_bundle_references`. Export
metadata displayed by the package UI includes the selected framework,
policy result ID, matrix version, and evidence anchor references. The
package UI exposes an authenticated CSV download via
`GET /api/reports/export?report_type=package&format=csv&framework_id={selected_framework_id}`
through the shared API download helper. Decimal fields serialize as
strings so frontend/CSV/E2E assertions never lose money precision.

### Multi-currency consolidation

Reports generate in a single base currency (user-configurable, default
SGD). FX rate application: **period-end rate** for balance-sheet items,
**average rate** for income-statement items, with calculated unrealized FX
gains/losses recorded separately. Manual valuation snapshots use the
requested balance-sheet `as_of_date`; historical balance sheets stay
date-bounded to the requested `as_of_date` for portfolio market-valuation
adjustments, while the current-day balance sheet uses the latest imported
brokerage snapshot when provider output normalizes a current statement to
a future period end. An average-rate fallback to a spot rate returns
`fx_warnings`; when an FX rate is unavailable after allowed
fallback/lazy-resolution, the affected currency is excluded from converted
trusted totals and the report returns an explicit partial warning
(`missing_fx_rate_partial_skip` / `missing_fx_revaluation_partial_skip`) —
reports never silently assume a 1:1 rate for a foreign currency. Core
report pages render non-empty `fx_warnings` visibly before the headline
KPI/cards, and the Balance Sheet page renders equation component detail
for `net_income`, `unrealized_fx_gain_loss`,
`net_worth_adjustment_gain_loss`, and `equation_delta`.

```python
from src.audit.money import ExchangeRate, Money, convert, to_money

def consolidate_amount(amount: Decimal, currency: str, target: str, date: date) -> Decimal:
    if currency == target:
        return to_money(amount)
    rate = get_fx_rate(currency, target, date)
    return convert(Money(amount, currency), ExchangeRate(currency, target, rate)).amount
```

**Balance sheet net worth sources** combine three classes:

| Source | Rule |
|--------|------|
| Journal lines | Aggregate posted/reconciled asset, liability, and equity account balances through the report date |
| Active portfolio positions | Add a market valuation adjustment per broker account equal to `current market value - ledger-backed position cost basis`; current-day reports may use the latest imported brokerage snapshot date to match `/portfolio/holdings` |
| Manual valuation snapshots | Add latest in-scope asset/liability snapshots as synthetic report lines; restricted retirement/benefit assets contribute when `include_restricted=true` |

Portfolio adjustments prevent double counting without removing broker
cash: if position cost basis already exists as a debit to the broker
account, only the market-value delta is added to assets; if no cost-basis
journal exists, the full market value is added. Manual valuation snapshots
use `include_in_total_net_worth` to decide inclusion, converted to the
report currency using the historical FX rate on `as_of_date`. Balance
sheet source classes also carry report-line provenance (see above): ledger
lines derive it from contributing journal source types, active portfolio
market adjustments are `derived`, manual valuation synthetic lines are
`manual`.

`unrealized_fx_gain_loss` is **not a balancing plug** — it's calculated
from foreign-currency asset/liability accounts by comparing `native
account balance * report-date spot rate` against `historical base-currency
cost from posted/reconciled non-revaluation journal lines`. Posted
`FX_REVALUATION` entries are excluded from both native balance and
historical cost so a prior revaluation doesn't change the next period's
nominal foreign-currency balance. `net_worth_adjustment_gain_loss` is the
explicit balancing component for non-ledger value added by portfolio
market adjustments and manual valuation snapshots — computed from those
added lines, not from the remaining balance-sheet delta.

### <a id="internal-transfer-net-worth-neutrality"></a>Internal-transfer net-worth neutrality

**Generalized invariant.** Net worth changes only via **external in/out**
(real income/expense), **market moves** (portfolio valuation), and **FX
revaluation**. **Internal (own-account) transfers cancel** — they move
money between the owner's own accounts and must not change net worth.

A matched cross-currency transfer (see [FX / cross-currency transfer
pairing](../reconciliation/readme.md#fx-cross-currency-transfer-pairing))
is classified **net-zero** (#1123 AC3): the transfer-**in** leg is *not*
income and the matching transfer-**out** leg is *not* expense — the only
net-worth impact is the transfer **fee**, a real external outflow.
Implemented by `classify_internal_transfer`
(`reconciliation/extension/fx_transfer.py`): `net_worth_delta = -fee` for
an internal transfer, `income - expense` otherwise.

This classification is wired into report generation (#1123 AC3, live):
`reporting._internal_transfer_adjustment` loads recorded `fx_conversions`
rows anchored to journal entries, re-validates each through
`pair_fx_legs` + `classify_internal_transfer`, and excludes the matched
legs from income/expense aggregation in both `generate_income_statement`
and cumulative balance-sheet net income — adding back only the (converted)
fee. A naively double-booked internal transfer therefore nets to zero in
the report except for its fee (`reporting/test_internal_transfer_e2e.py`).

**Source: recorded rows OR raw ledger** (#1123 AC2 live) — the adjustment
doesn't require a pre-seeded `fx_conversions` row; it also calls
`services/fx_transfer_discovery.discover_fx_conversions` to auto-discover
the same transfer pairs directly from raw `ASSET`-account journal lines
(see [FX / cross-currency transfer
pairing](../reconciliation/readme.md#fx-cross-currency-transfer-pairing)).
Discovered (in-memory) conversions merge with recorded ones and dedupe by
the unordered pair of anchored journal entries, so a transfer that is both
recorded and discoverable is never netted twice — a cross-currency
internal transfer booked purely as raw ledger lines is net-worth-correct
end to end with no manual conversion row
(`reporting/test_fx_ledger_autodiscovery_e2e.py`). Discovery is
conservative — only unambiguous 1:1 matches net, biasing toward
*under*-netting.

**FX gain/loss is attributed to revaluation over time, not the conversion
event** (#1123 AC4). A same-day round-trip conversion A→B→A nets ~zero
realized P&L (minus fee/spread) because the market rate hasn't moved
(`round_trip_realized_pnl == -fee`); any later divergence between the
recorded conversion and a subsequent valuation is a holding-period
revaluation routed through `FX_REVALUATION`, never booked as a
conversion-event income/expense line — proven live through
`reporting/test_fx_ledger_autodiscovery_e2e.py::test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report`.

### Design constraints

Recommended: report generation is read-only and never modifies the ledger;
always validate the accounting equation before rendering; cache report
results with date-based invalidation; pre-fetch all FX rates in bulk before
starting a report calculation to avoid N+1 queries; cap trend data points
at 366 (one year of daily data); include market-valuation deltas (not full
portfolio values) when the account already has ledger cost basis; calculate
unrealized FX from historical cost, never from the accounting-equation
remainder; missing FX data produces an explicit partial-report warning and
excludes the unconvertible currency from trusted converted totals.

Prohibited: never hardcode account codes in report logic; never silently
generate converted totals for foreign-currency data without a real FX rate
or explicit partial warning; never double-count a broker account by adding
both its ledger cost and full market value; never let posted
`FX_REVALUATION` entries change native foreign-currency balances.
