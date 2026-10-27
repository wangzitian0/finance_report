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
>   (`package_document.py`, `report_traceability.py`, `report_package.py`,
>   `reporting_snapshot.py`), the calculation primitives
>   (`reporting_calc.py`), and the injected FX seam (`fx_gateway.py`).
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
reporting assembles reports from ledger-owned trust facts; `pricing` owns
valuation-observation staleness facts. This contract's
`manual-valuation-excluded-from-reporting-language` invariant pins that
boundary so it cannot silently drift back.
Pricing also owns manual-valuation line naming. Reporting consumes the produced
lines and the ledger-owned `worst_confidence_tier`; it defines neither helper.

## Ubiquitous language

- **`ReportSnapshot`** — the aggregate root: a generated, framework-anchored
  report as of a period, holding its own provenance/traceability lineage.
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
traceability appendix, section payloads, and the exact structured
statement-disposition policy snapshot in `report_data`. The package consumes
that snapshot from extraction's published boundary; it does not infer policy
version, rollout mode, thresholds, or deployment commit from current settings.
Reopening a package returns the frozen disclosure even if runtime configuration
has since changed.

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
statement** — cash flow is a journal-entry event projection, not a projection
of every account's period movement. An activity exists only when an eligible
entry touches an exact cash identity. Income/expense counterparts are exact
operating evidence. Non-operating activity requires a supported event semantic
on an anchored `SYSTEM` journal event or a 2-line anchored `bank_txn` event.
For `bank_txn` events, `LOAN_PRINCIPAL` on a `LIABILITY` account maps to
`Financing`, and `INVESTMENT_TRADE` on an `ASSET` account maps to `Investing`.
`INVESTMENT_SALE` stays in `unclassified_cash` because statement sale proceeds
book against Brokerage Custody Cash (`ASSET`) and must not double-count
`investment_sell` entries. Caller-supplied event strings on manual entries have
no classification authority. Broad asset, liability, and equity types do not
authorize a category because they cannot distinguish investments from
receivable settlement or financing from payable settlement. Unsupported and
mixed events remain in `unclassified_cash` with an explicit unproven reason
instead of being guessed. Non-cash accruals and liability-financed asset
purchases therefore emit no cash activity, while their later settlements still
enter the cash bridge. Direct cash-to-cash and Processing-mediated internal
transfers are neutral because the ledger-defined Processing identity is a cash
equivalent for this projection.

`beginning_cash` and `ending_cash` value the selected cash identities at the
period bounds. The additive cash bridge proves that classified activity,
unclassified cash, and the separately disclosed FX effect equal
`ending_cash - beginning_cash`. Missing FX evidence fails report generation;
it is never silently treated as zero. Each classified or unclassified event
exposes its exact journal-entry/line anchors, source provenance, decision
authority and anchor, and event semantics. Every loader predicate requires both
entry and account tenant ownership. Any contributing event without an anchored
decision keeps the result explicitly unproven even when its cash identity is
exact. Package readiness consumes this proof state as a blocking section
invariant, so lineage visibility or a balanced bridge alone cannot authorize,
freeze, reopen, or export an unproven cash-flow section as trusted.

`GET /reports/cash-flow` returns `CashFlowPreview`, the projection
`cash_flow_preview(document)` of the complete document (#2583 S10). Each section
has one line for each activity, description and account (`cash_flow_line_id`),
with the sum and the count of its items. The preview has no per-event lineage;
`lineage_summary` counts the lineage records. `GET /reports/cash-flow/line-events`
returns the records of one line page by page, in document order, with the entry
date, the memo and the cash movement. Unclassified records use the line id
`unclassified`. Opening-stock records use the line id `opening_stock`. The
document, the preview lines and the pages come from one builder. The CSV export
and the package snapshot keep the complete document. The event read selects
columns, not ORM rows: one year of data has about 2000 lines.

For a trusted `PersonalReportPackageDocument`, cash/bank identity is supplied as
typed `PackageCashInputs` derived from authoritative bank-statement
contributions and their exact custody `account_id` refs. The package path never
classifies cash from `Account.name`; a missing or unproven cash input blocks
trusted output. Standalone analytical cash-flow views retain a bounded
compatibility fallback over the extraction-created `AUTO-BANK` account code and
legacy cash-name vocabulary; it cannot authorize, persist, reopen, or export
a package. Brokerage cash decomposition remains a separate evidence problem: a
brokerage container is not assigned a global binary cash role.

**Net worth time-series** — `GET /reports/net-worth/timeseries?from=...&to=...&granularity=daily|monthly&include_restricted=...`
returns `{date, total_assets, total_liabilities, net_worth, currency}`
points; `daily` is capped at 366 points, `monthly` uses the period end
date, and for the same stored FX rates and the same `include_restricted`
scope each point equals the balance sheet on that point's date
(AC-reporting.net-worth-timeseries.3). It does not
compute net income, so an FX miss on an income or expense line does not fail
it. The series does not build one
balance sheet per point (#2583). Two grouped queries give the ledger balance
before the first point and the daily movements; a running sum gives each
point, at the spot FX rate of the point date (`get_exchange_rate_series`).
Manual valuations come from `build_manual_valuation_lines_series`. Positions
are read once; a point with held positions uses the balance-sheet portfolio
valuation for those positions. A `monthly` series keeps at most 366 months
(the latest ones) and starts at the first month with a non-zero total.

**Net worth allocation schedule** — `GET /reports/net-worth/allocation?as_of_date=...&currency=...&include_restricted=...`
is report-owned (not portfolio-owned) because it must reconcile ledger
accounts, active portfolio market-value adjustments, manual valuation
snapshots, and liabilities to the same net worth total as the balance
sheet. `value` is signed in the report currency (assets positive,
liabilities negative; the sum of all rows equals `net_worth`);
`percentage_of_net_worth = value / net_worth * 100` (2dp, `null` when net
worth is zero); rows group by `asset_class × liquidity_class ×
source_currency` and retain drill-through `source_lines`. A source line
carries `source_type`, `source_id`, `label` and `value`, and no link: the
app opens the lineage drawer for a `ledger_account` and the evidence drawer
for a `manual_valuation` (AC-reporting.net-worth-scope.8). Portfolio
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

The stable delivery surface is one versioned `PersonalReportPackageDocument`,
not a directory of section endpoints. `GET /api/reports/package` builds the
current preview document and returns its bounded projection,
`PersonalReportPackagePreview` (#2583 S8). The projection keeps every section.
Each traceability line keeps its metadata, its anchor states and a `detail_count`
per anchor. It has no identifiers, no details and no input manifest entries;
`readiness.input_coverage` gives the manifest counts. At one year of activity the
preview is about 60 KB; the complete document was 3.9 MB.
`GET /api/reports/package/line-details` (one line anchor) and
`GET /api/reports/package/manifest-entries` return those lists page by page with
the shared `limit`/`offset` bounds. They read the same contribution set as the
document, without the statement sections, and the same appendix builder, so each
page equals the matching slice of a frozen snapshot of the same period. These
two routes are pages of the one document, not separate package artifacts.
Runtime package journeys read annualized income, notes and traceability counts
from the preview, and the traceability details and manifest entries from these
pages, with their independent numeric assertions intact; the consumer-closure
proof includes these E2E callers.
`POST /api/reports/package/generate` persists the complete document, details and
manifest included; the snapshot list, selected reopen, and selected JSON/CSV
export routes read only that frozen document. Required document sections are:

| Section ID | Owner |
|---|---|
| `balance_sheet` | reporting |
| `income_statement` | reporting |
| `cash_flow` | reporting |
| `investment_performance` | portfolio, adapted by reporting |
| `annualized_income_long_term` | reporting |
| `notes` | reporting |
| `traceability_appendix` | reporting |

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

The package page exposes independent period start and end dates for preview
and generation. The initial default retains the prior calendar-year window
(leap-day clamped); changing the start selects a custom window, such as
March 1–31. Point-in-time sections use the selected end as `as_of_date`.
Both dates are part of the preview cache identity and the exact same period
is sent when generating a snapshot. Missing, invalid, or reversed dates
produce a local error without preview or generation requests. The reports
overview consumes the same period-request builder with its existing default.
Reopening restores the saved period, and the cover displays the frozen
document's original as-of date even when it differs from its end date.
JSON/CSV downloads remain addressed by the selected snapshot ID; editing
dates starts a new preview and never rewrites a saved artifact.

Package readiness is a deterministic field of the document and is produced
only by `PackageAssembler`. `assemble` and `evaluate_readiness` share one
evaluation step, so both return the same readiness. `evaluate_readiness` does
not build the traceability appendix, the notes, or a package decision, because
readiness does not read them (#2583). The evaluation step opens one
`shared_current_authority` block, so its current-authority reads (opening
positions, journal contributions, input manifest) share one read of the audit
projection (#2602). The manifest-entries page does the same. Workflow and advisor consume
`current_package_readiness`; frontend surfaces render the document.
None may retain a readiness route, service, or local derivation. A document is
`ready` only when exact current contribution decisions and section invariants
pass; otherwise it is `blocked`. Only a persisted package decision may set the
frozen document status to `trusted`.

Net-income invariants respect each section's period: the balance sheet is
cumulative through `as_of_date`, while the income statement covers
`start_date` through `end_date`. Each is checked against its corresponding
ledger aggregation, including that period's FX averaging window. Prior-period
income or expenses do not themselves block a monthly package. Subtracting two
cumulative, independently FX-restated balance sheets is not a substitute for
the selected-period income projection. An inconsistent section still blocks
readiness as `statement_net_income_mismatch`; frozen reopen/export preserve
the selected document's values without recalculation.

The embedded framework-policy result is read-only and fingerprints the selected
framework, matrix version, period, decisions, and gaps. Package assembly must
consume that result and may not infer framework-specific authority from raw
portfolio rows. The annualized-income/long-term section, notes, and traceability
appendix are likewise fields of the same document rather than independently
fetchable package artifacts.

Required note IDs are `basis-of-preparation`,
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

The traceability appendix is a pure projection of the exact
`PackageSectionContribution` collection used to build the document manifest.
Each line maps one section/line to source and ledger anchors: `line_id`,
`section_id`, `label`, optional `amount_field`/`currency_field`,
`source_state`, `source_anchor` (`state` ∈ `{available, unavailable,
not_applicable}` + identifiers), and `ledger_anchor` (same shape). Details
carry the contribution input reference, amount/currency when present,
current decision id, review state, and reason code. The preview replaces the
identifiers and details of each anchor with `detail_count`; the package page
loads the details of one line when the user opens it.

For a cutoff inside a statement period, reporting retains its exact current
source decision for immutable transactions dated within the selected period
and cutoff. Such movement evidence supports flow sections and traceability,
not the statement's future closing balance or positions. The immutable result
and reviewed envelope are never rewritten. Closing-stock selection continues
to require the effective statement end on or before the report cutoff.
A source anchor with no selected details is `unavailable` with reason
`no_selected_source_contribution`; static template metadata is not evidence.

Every authoritative contribution carries one audit `TraceDecisionRef` with its
decision id, expected target, and expected assertion. `PackageAssembler` accepts
it only when the tenant-scoped current projection matches all coordinates;
missing, stale, cross-scope, target-mismatched, and assertion-mismatched inputs
remain visible as unproven and cannot enter the trusted manifest.

The frozen package decision is bound to the document by reporting's published
`personal_report_package_target` canonicalizer. `PackageAssembler` uses that
function when it emits the decision; terminal consumers use
`personal_report_package_decision_ref` to reconstruct the exact decision id,
target, and assertion from the selected frozen document. Consumers must not
copy the semantic hash or treat an opaque decision id as package authority.

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

**Export contract** — the selected frozen snapshot supports `json`/`csv` at
`GET /api/reports/package/snapshots/{snapshot_id}/export`; CSV columns include `package_id`,
`section_id`, `line_id`, `label`, `amount`, `currency`, `source_state`,
`selected_framework_id`, `framework_policy_result_id`,
`framework_policy_matrix_version`, `evidence_bundle_references`. Export
metadata displayed by the package UI includes the selected framework,
policy result ID, matrix version, and evidence anchor references. Decimal fields
serialize as strings so frontend/CSV/E2E assertions never lose money precision.

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
| Manual valuation snapshots | Add latest in-scope asset/liability snapshots as synthetic report lines; the scope rule is `pricing.split_net_worth_scope` (see **Net worth scope** below) |

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

<a id="net-worth-scope"></a>**Net worth scope (#2645).** One net worth serves
Home, the `/reports` Overview, the Balance sheet tab, the net worth chart and
Portfolio. Each one reads `total_assets - total_liabilities` of
`generate_balance_sheet` (the series computes the same totals with a running
sum) for one as-of date and one `include_restricted` scope
(AC-reporting.net-worth-scope.1).

- The default scope of each net worth route and of the app is the full net
  worth: `DEFAULT_INCLUDE_RESTRICTED = True` (`reporting/base/types.py`, read by
  the balance sheet, its diagnostics and export, the allocation, the series and
  `/reports/data-quality`) and `DEFAULT_INCLUDE_RESTRICTED = true` in
  `hooks/useReportFilters.ts` (Home, `/reports`, Portfolio) (AC-platform.29.9).
- `include_restricted=false` is the liquid scope. `pricing.split_net_worth_scope`
  is its only definition: it excludes each restricted or illiquid asset
  valuation and each liability valuation whose allocation class (a fixed map
  from the component type) is the class of an excluded asset. Only
  `mortgage_balance` shares a class with an asset type (`real_estate`), so a
  mortgage valuation leaves with an excluded property valuation
  (AC-pricing.manualvaluation.12).
- Limits of the rule (#2659): no record links one liability to one asset. A
  ledger liability account, for example a mortgage kept as a loan account,
  always counts. When one property valuation is excluded, every mortgage
  valuation leaves, also the mortgage of a property valuation set to liquid.
  The rule reads the valuations current on each as-of date, so a mortgage
  valuation older than its property valuation counts until the property date.
- A scoped response returns `excluded_holdings`: one row per excluded asset
  class with its excluded assets, excluded liabilities and net. Home, the
  Balance sheet tab and Portfolio label the figure "Liquid net worth" and list
  each row (AC-reporting.net-worth-scope.3, .5, .7). The totals do not depend
  on these rows: an excluded valuation with no FX rate gives its row null
  amounts and a warning, and the report does not fail
  (AC-reporting.net-worth-scope.9). An included valuation with no FX rate fails
  the report as before (AC-reporting.net-worth-scope.10).
- The Balance sheet tab shows `net_worth_adjustment_gain_loss` on its own
  equity line, "Manual and market valuations". The "FX and translation (CTA)"
  line carries only `unrealized_fx_gain_loss` and `cta_adjustment`
  (AC-reporting.net-worth-scope.6).
- The personal report package presents the liquid scope by default
  (`PACKAGE_INCLUDE_RESTRICTED = False`, read by `GET /reports/package`,
  `PackageAssembler` and `assemble_framework_balance_sheet`; the generate body has
  no scope default, so an absent value reads the constant in the route and the
  app sends none, AC-reporting.net-worth-scope.12, .16). Its balance sheet
  carries `excluded_holdings`, and its `restricted-asset-treatment` note names
  each excluded class with its net, assets and liabilities
  (AC-reporting.net-worth-scope.11). The document context records the scope
  (`context.include_restricted`, AC-reporting.net-worth-scope.20). The Package
  tab card takes its label from it: "Liquid net worth" with the excluded
  classes, or "Net worth" (AC-reporting.net-worth-scope.15). A snapshot frozen
  before #2645 records no scope; its liquid figures follow the older rule, so
  the card shows no net worth for it (AC-reporting.net-worth-scope.17).
- An FX gap on a restricted holding does not fail a report:
  - `/reports/data-quality` runs the equation check without restricted holdings
    and adds a `RESOLVE_FX_RATE` action item, titled by the cause (missing rate
    or failed conversion), with no score boost; the score does not change
    (AC-reporting.net-worth-scope.13, .18). Only a pricing-family FX error falls
    back; another error, and an error of the second run, fail as before
    (AC-reporting.net-worth-scope.19). The equation result does not depend on
    the scope, because a manual valuation adds the same amount to one side and
    to `net_worth_adjustment_gain_loss`.
  - The annualized schedule lists the holding in its own currency, leaves it
    out of `restricted_fair_value_total`, names it in
    `restricted_fair_value_total_excludes` (structured rows: the
    `conversion_warning` shape plus `amount`), and the package readiness has the
    `restricted_holding_fx_unavailable` blocker
    (AC-reporting.net-worth-scope.14). An FX gap on an income line still fails.

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
the report except for its fee (`tests/tooling/test_benchmark_scenario_suite.py`).

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

### Report integrity across account and source lifecycles

Framework policy matrix version `2.0` presents the exact ledger Processing
identity separately as **Cash in transit**, including zero and unsettled
balances. It remains a cash equivalent for transfer neutrality; ordinary
accounts do not acquire this meaning from their name or an arbitrary system
flag.

Period income presentation uses the accepted `economic_category` frozen into
the posted journal command. The same account may contribute salary, interest,
or other categories independently. The L1 registry owns the category-to-line
mapping for both frameworks. Unspecified, unsupported, or unanchored categories
remain **Other income** or **Other expenses**; account names and broad
INCOME/EXPENSE types never assert investment income or brokerage fees. Ordinary
`FEES` remain general fees and charges. Framework splitting preserves each
account's rounded total: any sub-cent FX rounding residual is assigned to its
largest category, with report-line ID as a stable tie-break. Frozen packages
retain their original policy version and report lines when reopened/exported.

Account archival controls current operational selection, not the validity of
posted historical facts. Balance sheets, income statements, cash projections,
framework mappings, portfolio cost/market-value contributions, and FX
revaluation retain archived accounts for the same historical date and period.

Opening cash consumes ledger's `list_opening_positions` projection, including
its exact current decision and effective date. An authoritative opening dated
on the report start establishes beginning cash and is excluded from economic
cash flow. The same-day journal/source anchors remain visible. Explicit zero
initializations need no journal, but their opening-position decision still
belongs to the package input manifest. Unproven positions cannot authorize a
package.

A first opening evidenced strictly inside the requested period does not prove
cash at the earlier report start. The report remains unproven with
`opening_coverage_starts_after_period`, discloses its
`cash_bridge.opening_stock_adjustment`, and excludes this stock from
`net_cash_flow`. The bridge is classified activity + unclassified cash + FX
+ opening stock adjustment = ending cash - beginning cash. Selecting a period
whose start is covered resolves that coverage limitation without inventing
historical wealth or current-period receipts. Missing field values on old
snapshots remain absent during serialization so frozen exports stay compatible.

The cash-flow page, package summary and standalone CSV disclose any opening
balance adjustment during the period. A coverage gap labels beginning cash as
the known amount; unproven authority never receives a verified arithmetic badge.
The CSV carries the same proof state and reasons as the report.

The live GXS browser journey also reads a midperiod package from the same uploaded
source, independently checks cutoff amounts, and requires concrete source decision
anchors (`AC-reporting.report-integrity.8`). Full-month JSON/CSV snapshot assertions
remain separate from this live midperiod projection.

### Unified period-first three-statement cockpit and chart scales (#2548, #2621)

- **One dimension bar (`AC-reporting.fe-period-cockpit.1`, `.2`)**: `ReportDimensionBar` sets the period preset (`1M`, `1Q`, `1Y`, `YTD`, `3Y`, `All`) or a custom start and end, steps to the previous or next period, and sets the currency. Home and every `/reports` tab show it. The URL holds these dimensions (`useReportFilters`: `period`, `start`, `end`, `currency`, `include_restricted`, `tab`). A link with a `period` or a `start` does not depend on server data: with an `end` it reproduces its dates exactly, and without an `end` it ends today. The default view (no `period` and no `start`) also depends on the coverage start that the server returns.
- **`/reports` tabs (`AC-reporting.fe-period-cockpit.3`)**: Overview, Balance sheet, Income statement, Cash flow and Full package are tabs of one page. The old routes `/reports/balance-sheet`, `/reports/income-statement`, `/reports/cash-flow` and `/reports/package` redirect to `/reports?tab=<name>` and keep their query (`AC-meta.fe-reports-tabs.1`).
- **Three-statement cockpit (`AC-reporting.fe-period-cockpit.4`, `.5`)**: `StatementCockpit` on Home and on the Overview shows net worth and its change in the period (the balance sheet at the period end minus the opening balance sheet of `ReportFilters.openingDate`), income, expenses, net income and savings rate, and operating, investing, financing and net cash change. When drill-down rows exist, a segmented control selects one statement and a row of its largest lines opens `AccountLineageDrawer`; when all statements have zero drill-down rows, the switcher is omitted (#2730).
- **The cash coverage start bounds the default view and `All`, and exposes the latest statement end (`AC-reporting.fe-period-cockpit.7`, `.8`, `.10`, `.11`, `AC-reporting.2646.1`, `.2`, `.3`, `AC-reporting.2726.1`, `.2`, `.3`)**: `report_coverage` returns the latest opening position of a cash account on or before the date, the names of the cash accounts whose opening position is on that day, and `latest_statement_end` (the latest approved statement period end on or before `as_of_date`). It reads the cash accounts of both cash-flow callers: `GET /reports/cash-flow` (by account name) and the report package (bank custody accounts). `coverage_bank_custody_account_ids` reads, in one query, a deliberate superset of the package cash set: the custody accounts of every bank statement of the user that starts on or before the date, in any status. The package keeps a statement by the trace decision of its current source result, and a statement can stay parsed with an authoritative decision (a confirmed envelope before approval, an auto-approval that falls back to review). A statement that closes after the date counts too, because the package reads its movement in the period. A wider set can only move the bound later; it never causes the coverage blocker. `opening_coverage_start` is the one function that both the bound and the cash-flow check `opening_coverage_starts_after_period` read. A card or brokerage statement does not move the bound, and an opening balance before the first statement keeps its history. `GET /reports/coverage?as_of_date=<period end>` serves `coverage_start`, `limiting_accounts`, and `latest_statement_end`. Its SQL count does not grow with the number of statements. The default view and `All` apply the bound: they start no earlier than `coverage_start` (with `2000-01-01` as the fallback when no cash opening exists) and have no previous period then. Their opening balance sheet is that day, the cockpit states that day under Change in period, and in the default view a note under the dimension bar names the limiting accounts and links to Add an opening balance (`/settings?tab=accounts`). When `latest_statement_end` precedes the default `1Y` start date, a one-click note under the dimension bar jumps the period end to `latest_statement_end` (#2726). A chosen preset writes `period` to the URL, `1Y` too. An explicit preset other than `All` and a custom period keep their full period and their previous period, and do not request the coverage. In `compute_personal_data_quality`, the 12-month `Temporal Continuity Timeline` anchors at the latest statement period end on or before `as_of_date` when statements exist (#2726). `OpeningBalanceModal` marks the coverage start and every ledger-derived read stale after it records opening balances. `current_package_readiness` bounds its 365-day window the same way, so the workflow status shows no coverage blocker for a new user.
- **One action banner (`AC-reporting.fe-period-cockpit.6`, `.9`)**: Home shows workflow items only as `HomeActionBanner`, and only when an item needs the user. The confidence queue comes first: the banner names its count and its first item and links to `/audit?tab=needs-you`. A workflow blocker shows only when the queue is empty. The `/audit` Needs you badge shows the same count.
- **Chart axis scales and share labels (`AC-reporting.2548.3`)**: `BarChart` and `PieChart` render compact axis scale bounds, net period deltas, and segment percentage shares while preserving accessible SVG/DOM roles.
