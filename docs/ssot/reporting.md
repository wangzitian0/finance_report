# Financial Reporting SSOT

> **SSOT Key**: `reporting`
> **Core Definition**: Financial report generation logic, report types, and calculation rules.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Report Logic** | `apps/backend/src/services/reporting.py` | Report generation |
| **FX Revaluation** | `apps/backend/src/services/fx_revaluation.py` | Historical-cost unrealized FX calculation |
| **FX Rates** | `apps/backend/src/services/fx.py` | Spot and average-rate lookup, fallback warnings |
| **Report Templates** | `apps/frontend/src/app/reports/` | Report pages and layouts |
| **Visual Components** | `apps/frontend/src/components/charts/` | Chart components |

## 1.1 Automated Report Preparation Contract

Reports are prepared from trusted ledger facts, reviewed records, owned
valuation snapshots, and market data with explicit source basis. Once the user
has uploaded supported source documents, report preparation should assemble the
required sections automatically wherever deterministic rules and registered ACs
exist.

Automation examples include multi-currency conversion, investment valuation,
annualized income, ESOP/RSU and other long-term compensation schedules, fixed
recurring expense accrual or pre-deduction presentation, report-readiness
blockers, notes, and source links. If an input is missing, stale, ambiguous, or
outside the implemented contract, the report must disclose the limitation or
block readiness instead of silently filling the gap.

### 1.1.1 Source Intake UI Contract

The Upload surface may consume the required source classes from
`docs/ssot/source-coverage-matrix.yaml` as a user-facing checklist before
statement upload. Frontend routes may map those backend ingestion paths to the
existing user workflows (`/upload`, `/portfolio/evidence`, `/journal`), but the
frontend does not own source-trust classification. Package readiness and
source-trust endpoints remain authoritative for whether a source class is a gap,
manual-trusted, imported/supported, or ready for trusted report output.

Manual evidence classes such as ESOP/RSU plans, property statements, liability
statements, and manual records must stay visibly manual-trusted. The Upload UI
must not imply they are automatically imported or parsed when the underlying
contract is an explicit user-entered evidence path.

### 1.2 Report Snapshot Determinism

`report_snapshots` stores generated ADS report payloads. Regeneration may keep
historical non-latest rows for the same report date, but the database prevents
conflicting published state:

- point-in-time reports have at most one `is_latest=true` row per
  `(user_id, report_type, as_of_date)`;
- range reports have at most one `is_latest=true` row per
  `(user_id, report_type, start_date, as_of_date)`;
- range snapshots require `start_date <= as_of_date`.

Personal report package snapshots use the same Layer 4 table with
`report_type = package`. They freeze the package artifact rather than a
classification-rule version, so `rule_version_id` may be null for package rows.
Generation stores the package period, currency, selected framework, readiness
state, source-trust summary, framework policy result, traceability appendix, and
section payloads in `report_data`.

Package snapshot endpoints:

- `POST /api/reports/package/generate` creates a saved package snapshot for the
  requested `framework_id`, `start_date`, `end_date`, `as_of_date`, and
  `currency`.
- `GET /api/reports/package/snapshots` lists the current user's saved package
  snapshots.
- `GET /api/reports/package/snapshots/{snapshot_id}` reopens the saved payload
  without recalculating live report data.
- `GET /api/reports/package/snapshots/{snapshot_id}/export?format=json|csv`
  exports the saved snapshot. JSON and CSV export must be derived from
  `report_data`, not from live report endpoint recalculation.

The export endpoints (`GET /api/reports/export` and the snapshot export above)
return a bare `StreamingResponse`, so their media type and attachment header are
declared by the typed contract `ExportStreamEnvelope`
(`apps/backend/src/schemas/streaming.py`). The envelope constrains the media
type to `text/csv` or `application/json` and renders
`Content-Disposition: attachment; filename=...` from a validated filename. This
describes the existing wire behavior without changing it (EPIC-006 AC6.33).

Readiness gates the generated artifact status. If readiness is `ready`,
`generated`, or `stale` with zero blockers, the snapshot is `trusted`; blocked,
processing, or draft readiness can only create a `draft` snapshot. Draft
snapshots are still immutable and exportable, but consumers must not describe
them as trusted output.

---

## 2. Report Types

### 2.1 Balance Sheet (Statement of Financial Position)

Shows assets, liabilities, and equity at a specific point in time.

```
┌─────────────────────────────────────────────┐
│              BALANCE SHEET                   │
│              As of YYYY-MM-DD                │
├─────────────────────────────────────────────┤
│ ASSETS                                       │
│   Current Assets                             │
│     Cash & Bank              $XX,XXX         │
│     Investments              $XX,XXX         │
│   Non-Current Assets                         │
│     Real Estate              $XX,XXX         │
│   ─────────────────────────────────          │
│   Total Assets               $XXX,XXX        │
├─────────────────────────────────────────────┤
│ LIABILITIES                                  │
│   Current Liabilities                        │
│     Credit Cards             $X,XXX          │
│   Non-Current Liabilities                    │
│     Mortgage                 $XX,XXX         │
│   ─────────────────────────────────          │
│   Total Liabilities          $XX,XXX         │
├─────────────────────────────────────────────┤
│ EQUITY                                       │
│   Net Worth                  $XXX,XXX        │
├─────────────────────────────────────────────┤
│ Total Liab + Equity          $XXX,XXX        │
│ (Must equal Total Assets)                    │
└─────────────────────────────────────────────┘
```

**Validation**:

```
Total Assets =
  Total Liabilities
  + Total Equity
  + Net Income
  + Unrealized FX Gain/Loss
  + Net Worth Adjustment Gain/Loss
```

#### 2.1.1 Opening Balances (Year-Start Positions)

A balance sheet built only from imported statement activity is incomplete: an
everyday user who starts tracking mid-life has real assets and liabilities that
predate their first uploaded statement. The **guided opening-balance flow**
([#949](https://github.com/wangzitian0/finance_report/issues/949), AC2.15.x)
establishes those starting positions so the as-of balance sheet is not silently
understated.

Semantics (the contract the balance sheet relies on):

- **One balanced entry.** `POST /api/accounts/opening-balances` posts a single
  journal entry that increases each supplied account to its opening balance on
  its normal side (assets/expenses debited, liabilities/equity/income credited).
  The net is offset into a **system Opening Balance Equity account** so the entry
  balances and the accounting equation holds (AC2.15.1, AC2.15.2). Opening Balance
  Equity surfaces inside the balance sheet's `EQUITY` section, not as an asset or
  liability.
- **A starting position, not a delta.** An opening balance is rejected when an
  affected account already has posted activity *before* the opening date, so the
  posted amount can never stack on top of an existing balance (AC2.15.4). It
  establishes where the account *was*, then statement imports take over.
- **Base currency only.** Opening balances are accepted only in the report base
  currency, with a clear error instead of a confusing downstream FX-rate failure
  (AC2.15.5); a referenced account whose currency differs from the request is
  rejected so journal lines cannot be mis-stamped (AC2.15.6).
- **User-managed accounts only.** Even though the entry is SYSTEM-typed (it
  touches the system equity account), the request may only target user-managed
  accounts — a system account such as Processing cannot be seeded this way
  (AC2.15.3, AC2.15.7).

Because opening balances are ordinary posted journal entries, every downstream
report (net-worth time-series, cash-flow opening position) reads them through the
same ledger path — there is no separate "opening balance" report code path.

> Mechanics of the posting (account resolution, equity offset) are owned by
> [`accounting.md`](accounting.md); this section owns only how the resulting
> positions present in the balance sheet.

### 2.2 Income Statement (Profit & Loss)

Shows income and expenses over a period.

```
┌─────────────────────────────────────────────┐
│            INCOME STATEMENT                  │
│            Period: YYYY-MM to YYYY-MM        │
├─────────────────────────────────────────────┤
│ INCOME                                       │
│   Salary                     $XX,XXX         │
│   Investment Income          $X,XXX          │
│   ─────────────────────────────────          │
│   Total Income               $XX,XXX         │
├─────────────────────────────────────────────┤
│ EXPENSES                                     │
│   Housing                    $X,XXX          │
│   Transportation             $X,XXX          │
│   Food & Dining              $X,XXX          │
│   ─────────────────────────────────          │
│   Total Expenses             $XX,XXX         │
├─────────────────────────────────────────────┤
│ NET INCOME                   $X,XXX          │
└─────────────────────────────────────────────┘
```

### 2.3 Net Worth Time-Series

Returns point-in-time balance sheet totals for dashboard history charts.

Endpoint:
`GET /reports/net-worth/timeseries?from=YYYY-MM-DD&to=YYYY-MM-DD&granularity=daily|monthly`

Response points:
`{date, total_assets, total_liabilities, net_worth, currency}`

Rules:
- `daily` granularity is capped at 366 points.
- `monthly` uses the period end date for each returned point.
- Each point reuses balance sheet FX conversion as of that point's date.

#### 2.3.1 Net Worth Allocation Schedule

Returns a point-in-time allocation schedule for the asset dashboard. The
schedule is report-owned, not portfolio-owned, because it must reconcile
ledger accounts, active portfolio market-value adjustments, manual valuation
snapshots, and liabilities to the same Net Worth total as the balance sheet.

Endpoint:
`GET /reports/net-worth/allocation?as_of_date=YYYY-MM-DD&currency=SGD&include_restricted=true|false`

Response object:

| Field | Rule |
|---|---|
| `as_of_date`, `currency`, `include_restricted` | Echo the valuation date, report currency, and restricted/illiquid inclusion policy |
| `total_assets`, `total_liabilities`, `net_worth` | Balance-sheet totals in the report currency; `net_worth = total_assets - total_liabilities` |
| `rows` | Signed allocation rows grouped by `asset_class × liquidity_class × source_currency` |

Row rules:

- `value` is signed in the report currency: asset rows are positive, liability
  rows are negative, and the sum of all row values must equal `net_worth`.
- `percentage_of_net_worth` is `value / net_worth * 100`, rounded to two
  decimal places; it is `null` when net worth is zero.
- `source_currency` is the original source currency for same-currency source
  groups; mixed-currency portfolio groups fall back to the report currency
  after conversion.
- `source_lines` retains drill-through metadata for the grouped contributors,
  including source type, source id when available, label, signed value, and an
  internal href.
- Portfolio ledger-backed cost basis is grouped with `public_equity`; broker
  account residual value after cost-basis split remains `cash`.
- Manual valuation component types map to allocation asset classes:
  property and mortgage components are `real_estate`; CPF/provident fund
  balances, retirement accounts, personal social-security account balances,
  long-term benefit assets, legacy long-term savings, and insurance cash value
  are `retirement_and_benefit_assets`; ESOP, RSU, and stock options are
  `restricted_comp`; tax refunds are `cash`; tax payable and generic liabilities
  are `liability`; other manual components are `other`.
- Asset-dashboard allocation surfaces that claim net-worth reconciliation use
  this report-owned schedule. The portfolio performance schedule remains the
  source for period return, unrealized market-value gain/loss, price freshness,
  and portfolio-only performance detail.

### 2.4 Cash Flow Statement

Shows cash movements by category.

```
┌─────────────────────────────────────────────┐
│           CASH FLOW STATEMENT                │
│           Period: YYYY-MM to YYYY-MM         │
├─────────────────────────────────────────────┤
│ Operating Activities                         │
│   Net Income                 $X,XXX          │
│   (Adjustments)              ($XXX)          │
│   ─────────────────────────────────          │
│   Net Operating Cash         $X,XXX          │
├─────────────────────────────────────────────┤
│ Investing Activities                         │
│   Investment Purchases       ($X,XXX)        │
│   Investment Sales           $X,XXX          │
│   ─────────────────────────────────          │
│   Net Investing Cash         ($XXX)          │
├─────────────────────────────────────────────┤
│ Financing Activities                         │
│   Loan Payments              ($X,XXX)        │
│   ─────────────────────────────────          │
│   Net Financing Cash         ($X,XXX)        │
├─────────────────────────────────────────────┤
│ NET CASH CHANGE              $X,XXX          │
└─────────────────────────────────────────────┘
```

Cash-flow balances and activities use two different accounting views:

- `beginning_cash` is the cumulative signed balance of cash/bank asset accounts before `start_date`.
- `ending_cash` is the cumulative signed balance of cash/bank asset accounts through `end_date`.
- `net_cash_flow = ending_cash - beginning_cash`.
- Operating, investing, and financing activity rows are period movements only, converted into cash-flow signs: inflows are positive and outflows are negative.
- Activity totals must sum signed row amounts. They must not sum absolute values.

Cash-flow account classification:

- Operating: income and expense accounts.
- Investing: non-cash asset accounts.
- Financing: liability and equity accounts.
- Cash/bank asset accounts are used for beginning/ending cash and are not repeated as activity rows.

### 2.5 Investment Performance Schedule

The investment performance schedule is the report-ready portfolio input for the
personal financial-report package and is owned by EPIC-017. EPIC-005 consumes it
as the `investment_performance` report section.

The **asset-dashboard performance answer** is unrealized market-value gain/loss,
a simple return on cost basis valued at the schedule as-of date, and a
price-freshness flag, all derived from this schedule. `xirr`, `time_weighted_return`, and
`money_weighted_return` are analytical reporting measures only; surfaces must not
present them as the asset-dashboard answer (robo-advisor non-goal).

Endpoint:
`GET /api/portfolio/performance/report-schedule?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD&as_of_date=YYYY-MM-DD&currency=SGD`

If dates are omitted, the schedule defaults to year-to-date: `period_end`
defaults to today, `period_start` defaults to January 1 of the period-end year,
and `as_of_date` defaults to `period_end`.

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
market-data, dividend, and journal-entry facts into a reporting payload that can
be exported or embedded by EPIC-005.

If no holding snapshot exists on or before `as_of_date`, the schedule may use
active current holdings only when the same asset has a manual market-data
override dated after `as_of_date`. The response must disclose that
report-preparation evidence in `notes`, expose the override in
`data_freshness.manual_override_basis`, and include a `market_data_override`
source link. This fallback is report-only evidence and must not mutate ledger
state or weaken historical portfolio holding queries.

All monetary schedule fields are presented in the requested schedule currency.
Realized P&L uses the investment transaction date, dividend income uses the
payment date, current market value uses the schedule `as_of_date`, and holding
cost basis uses the managed position acquisition date. Mixed-currency schedule
amounts must not be added at raw nominal amounts.

### 2.6 Annualized Income Dashboard Summary

Endpoint:
`GET /api/income/annualized`

The dashboard annualized income summary uses the same trailing 365-day window
as the package schedule. It returns salary, bonus, dividend, total income,
currency, and as-of date for quick dashboard display.

Mixed-currency income lines must be converted into the dashboard reporting
currency before bucket and total aggregation. Non-reporting-currency income
uses the trailing-period average FX rate for the window.

### 2.6a Account Lineage Drill-Down

Powers Balance Sheet / Income Statement amount drill-down (EPIC-022). Returns
the individual posted/reconciled journal lines behind one account's report
balance so the UI can reach source transactions via the evidence-lineage graph.

Endpoint:
`GET /api/reports/account-lineage?account_id=UUID&as_of_date=YYYY-MM-DD&start_date=YYYY-MM-DD&currency=SGD`

- Applies the same status (`POSTED`/`RECONCILED`) and date filters as the
  aggregated reports; `start_date` is optional (used for period reports like the
  income statement), `currency` defaults to the account currency.
- Each line is Decimal-safe and signed with the same accounting rules as the
  balance (ASSET/EXPENSE debit positive; LIABILITY/EQUITY/INCOME credit
  positive), converted into the report currency.
- Each line exposes a `journal_line` identifier the UI hands to
  `GET /api/evidence/lineage` to reach the bank statement transaction, atomic
  fact, and source document. It is report-only and must not mutate ledger state.
- Accounts the user does not own return `404`.

### 2.6b Report Line Provenance

Balance Sheet and Income Statement `ReportLine` responses expose a normalized
optional `provenance` enum when the source basis is known:

| Value | Meaning |
|---|---|
| `imported` | The report line is fully backed by imported or user-confirmed statement/source entries. |
| `manual` | The report line is fully backed by user-entered facts, including manual valuation synthetic lines. |
| `derived` | The line is system-derived, market/FX adjusted, or combines multiple known provenance classes. |
| `null` | The backend cannot safely derive the line's source basis. |

For ledger account aggregates, provenance is combined from the contributing
posted/reconciled `JournalEntry.source_type` values after the same date and
status filters as the report amount. A single known class remains that class;
mixed known classes collapse to `derived`; unknown-only inputs remain `null`.
Portfolio market valuation adjustment lines are `derived`. Manual valuation
snapshot synthetic asset/liability lines are `manual`.

### 2.7 Personal Financial-Report Package Contract

Issue [#570](https://github.com/wangzitian0/finance_report/issues/570) owns the
stable package-level API/export contract. The contract defines how existing and
future report sections plug into one personal financial-report package; it does
not duplicate the calculation ownership of the supporting EPICs.

Endpoint:
`GET /api/reports/package/contract`

Contract response:

| Field | Rule |
|---|---|
| `package_id` | Always `personal-financial-report-package` |
| `version` | Contract version, currently `1.0` |
| `period_semantics` | Defines required `start_date`, `end_date`, `as_of_date`, `currency`, `framework_id`, and `decimal_serialization` semantics |
| `supported_frameworks` | Supported personal reporting framework IDs for package output |
| `selected_framework_id` | Selected framework ID when the request includes one; otherwise `null` |
| `framework_policy_endpoint` | Endpoint that returns the selected framework policy result consumed by package assembly |
| `sections` | Stable ordered section contracts with `section_id`, label, owner EPIC, period type, source endpoint, status, optional blocking issue, and Decimal-safe total fields |
| `export_contract` | Stable export formats and CSV column names for package consumers |

Required section IDs:

| Section ID | Owner | Source endpoint | Status |
|---|---|---|---|
| `balance_sheet` | EPIC-005 | `/api/reports/balance-sheet` | ready |
| `income_statement` | EPIC-005 | `/api/reports/income-statement` | ready |
| `cash_flow` | EPIC-005 | `/api/reports/cash-flow` | ready |
| `investment_performance` | EPIC-017 | `/api/portfolio/performance/report-schedule` | ready |
| `annualized_income_long_term` | EPIC-011 | `/api/reports/package/annualized-income-schedule` | ready |
| `notes` | EPIC-005 | `/api/reports/package/notes` | ready |
| `traceability_appendix` | EPIC-018 | `/api/reports/package/traceability` | ready |

The frontend package assembly route must present the package as a readable
deliverable, not only an API inventory. It renders a cover sheet and table of
contents before package output, using the selected framework, report date,
package id, and stable human section labels from this contract. Before a
framework is selected, the page must show setup guidance and the contract-backed
table of contents without loading framework-scoped output. While selected
framework data is loading, the page must reserve the package layout with
skeleton placeholders instead of a blank or text-only loading screen.
The loaded package has two presentation layers: the default reader layer uses
plain-language labels for evidence coverage, reporting basis, source coverage,
and traceability summaries; explicit audit-details disclosures retain raw
source-trust classes, blocker codes, framework policy result IDs, matrix
versions, line IDs, confidence tiers, review states, and export column metadata.
This is a presentation boundary only: the frontend must not drop or recompute
the policy, source-trust, readiness, traceability, or export facts.

Package readiness:

- Endpoint: `GET /api/reports/package/readiness`
- Owner: EPIC-019 Slice 5 (#639).
- Purpose: return the user-scoped readiness state and blocker links before the
  report package renders output. This endpoint is the package-owned fact source;
  workflow summary APIs may aggregate it but must not duplicate its derivation.
- Reports landing consumption: `/reports` may show a trust-first cockpit before
  report navigation by reading this endpoint through the shared frontend API
  client. The landing page may summarize `state`, `blocking_count`,
  `blockers`, and `source_trust_summary.gap_source_classes`, but it must not
  reimplement readiness priority, source-trust classification, or blocker
  derivation in frontend code.
- Response contract:
  - `package_id`: always `personal-financial-report-package`
  - `state`: closed enum of `draft`, `processing`, `blocked`, `ready`,
    `generated`, or `stale`
  - `selected_framework_id` in `source_summary` when a framework is selected
  - `framework_policy_inputs` in `source_summary`; this policy-specific count
    includes accounts, positions, manual valuations, and dividends, and excludes
    bank statements or journal entries that do not produce EPIC-020 policy facts
  - `framework_policy_decisions` and `framework_policy_gaps` in
    `source_summary` when framework policy is evaluated
  - `label` and `action_href`: primary UI state and next action; action links
    must be internal relative routes
  - `blocking_count`: sum of blocker record counts
  - `blockers`: ordered actionable blockers with `code`, `label`, `severity`,
    `count`, `reason`, and internal `action_href`
  - `source_summary`: counts of source records used to derive readiness
  - `generated_at`: latest package report snapshot timestamp, when available,
    modeled as a validated datetime and serialized as ISO 8601 JSON
  - `stale_since`: newest source timestamp when generated output is stale,
    modeled as a validated datetime and serialized as ISO 8601 JSON
- Determinism guard: duplicate canonical Processing system accounts (`code =
  1199`) are data corruption and must fail readiness derivation rather than
  selecting an arbitrary account balance.
- State priority:
  1. `draft`: no report-supporting inputs exist.
  2. `processing`: statements are uploaded or parsing and there are no blockers.
  3. `blocked`: one or more blockers exist.
  4. `stale`: a latest report snapshot exists, but source records changed after
     that snapshot.
  5. `generated`: a latest report snapshot exists and is not stale.
  6. `ready`: report-supporting inputs exist, no blockers exist, and no latest
     package snapshot has been generated yet.
- Required blocker codes:
  - `failed_parsing`: rejected statement parsing.
  - `pending_review`: source review is pending.
  - `balance_mismatch`: statement balance validation failed or has an
    unresolved validation error.
  - `reconciliation_blocked`: reconciliation match is pending review.
  - `consistency_check_blocked`: duplicate, transfer-pair, or anomaly check is
    pending.
  - `processing_account_unresolved`: Processing account balance does not net to
    zero after each line is converted into the base reporting currency.
  - `missing_source_coverage`: active asset or liability account lacks approved
    statement coverage or explicit source anchoring.
  - `unknown_source_anchor`: posted or reconciled journal entries have a
    `source_id` that cannot be resolved to a typed source record such as a bank
    statement transaction or atomic transaction.
  - `unsupported_framework`: selected package framework is unsupported.
  - `missing_framework_policy_result`: selected framework has package inputs but
    no matching structured policy result.
  - `unsupported_policy_domain`: selected framework cannot map a source fact to
    a deterministic v1 policy decision.
  - `framework_policy_missing_dimensions`: a policy decision lacks one of
    recognition, measurement, classification, presentation, or disclosure.
  - `framework_ai_suggestion_unreviewed`: AI-suggested policy fields have not
    been accepted as anchored structured fields.
  - `missing_valuation_basis`: manual/private valuations lack explicit basis
    text before trusted totals.
  - `stale_market_data`: listed security, ETF, mutual-fund, or bond positions
    lack synced provider or manual override prices dated within 90 days of the
    report date.
- The readiness derivation must be read-only. Opening the reports page must not
  create Processing accounts or other readiness artifacts.
- Framework policy blocker `action_href` values point to the existing
  `/reports/package` frontend route. The framework policy API endpoint remains
  backend-only unless a dedicated frontend route is explicitly added.

Framework policy result:

- Endpoint: `GET /api/reports/package/framework-policy`
- Owner: EPIC-020 for policy decisions; EPIC-005 consumes the result for
  package assembly.
- Inputs: `framework_id`, `start_date`, `end_date`, and `as_of_date`.
  `framework_id` defaults to `personal_us_gaap_like`; omitted period dates
  default to a trailing 365-day window ending at the selected as-of date.
- Output: a read-only `FrameworkPolicyResult` with stable `result_id`,
  selected framework ID, `matrix_version`, report period, required statements,
  policy decisions, line mappings, evidence anchors, and explicit gaps.
  `result_id` fingerprints the selected framework, matrix version, period, full
  decision content, and gap content. The endpoint derives the result from existing accounts, atomic
  positions, manual valuations, dividends, synced `StockPrice` rows, and manual
  `MarketDataOverride` rows. It must not mutate source records, journal entries,
  portfolio lots, market data, or report snapshots.
- Package assembly must consume this policy result and must not infer
  framework-specific report lines directly from raw portfolio market value.
- The `/reports/package` frontend route loads the package contract first, then
  requires the user to select `personal_us_gaap_like` or
  `personal_hkfrs_like` before loading readiness, framework policy, section
  output, or export metadata. The UI must pass the selected `framework_id` to
  the contract, readiness, and framework-policy package APIs; it must not
  silently use the backend framework-policy endpoint default.

Annualized income and long-term compensation schedule:

- Endpoint: `GET /api/reports/package/annualized-income-schedule`
- Period semantics: trailing 365 days ending at `as_of_date`; when omitted,
  `as_of_date` defaults to the request date.
- Income basis: `POSTED` or `RECONCILED` income journal lines in the trailing
  period, bucketed into salary, bonus, dividend, and total by income account
  name.
- Income totals are converted into the schedule reporting currency before
  bucket aggregation. Mixed-currency income lines must not be added at raw
  nominal amounts. Non-reporting-currency income uses the trailing-period
  average FX rate for the schedule window.
- Restricted compensation basis: latest as-of manual valuation snapshots for
  `esop`, `rsu`, and `stock_options` with `liquidity_class=restricted`.
- Liquid net worth default: restricted holdings are excluded by default and are
  only included through the balance-sheet restricted toggle. The
  `/reports/balance-sheet` endpoint and Balance Sheet page must both default
  `include_restricted=false`.
- Decimal fields serialize as strings; restricted fair-value totals are reported
  in the schedule currency using the as-of FX rate. Per-holding source currency
  remains visible.

Notes and disclosures:

- Endpoint: `GET /api/reports/package/notes`
- Status: `ready`.
- Required note IDs: `basis-of-preparation`,
  `reporting-period-and-currency`, `valuation-basis`,
  `investment-market-data`, `source-confidence-review`, and
  `restricted-asset-treatment`.
- Each note carries an owning EPIC, method basis, source state, applicable
  package sections, and disclosure text.
- The package-level non-compliance statement must say the report is not a
  regulated filing, not an audit opinion, not legal advice, and not tax advice.
- Standards-inspired accounting and listed-company references are used only as
  coverage and disclosure discipline. The notes must not imply regulated
  filing compliance.

Note ownership:

| Note ID | Owner | Source state |
|---|---|---|
| `basis-of-preparation` | EPIC-005 | `package_contract` |
| `reporting-period-and-currency` | EPIC-005 | `request_parameters` |
| `valuation-basis` | EPIC-011 | `manual_valuation_snapshots` |
| `investment-market-data` | EPIC-017 | `brokerage_imports_and_market_data` |
| `source-confidence-review` | EPIC-018 | `reviewed_journal_and_statement_links` |
| `restricted-asset-treatment` | EPIC-011 | `manual_valuation_snapshots` |

Traceability appendix:

- Endpoint: `GET /api/reports/package/traceability`
- Status: `ready`.
- The appendix is package-specific. It extends the existing
  `source-ledger-report-traceability` proof path without duplicating report
  calculations or changing ledger totals.
- Each appendix line maps one package section/line to source and ledger
  anchors:
  - `line_id`, `section_id`, `label`
  - optional `amount_field` and `currency_field` pointing back to the source
    report payload
  - `source_state`
  - `source_anchor` with `state`, source types, and identifier fields
  - `ledger_anchor` with `state`, entry statuses, and identifier fields
  - `review_state`
  - `confidence_tier`
- Anchor `state` must be explicit: `available`, `unavailable`, or
  `not_applicable`. Missing anchors are not an acceptable representation for
  trusted totals.
- When called with a current user and `start_date` / `end_date` / `as_of_date`,
  the appendix must add privacy-safe `identifiers` to anchors where source
  records exist. Dynamic identifiers can include statement transactions,
  journal entries/lines, brokerage atomic positions, brokerage document IDs,
  market price overrides, dividend income records, and manual valuation
  snapshots. The endpoint may return the static taxonomy without identifiers
  only when no request-scoped database context is available.
- Trusted package totals must expose source and ledger anchors unless the line
  is an explicit manual input, such as restricted compensation fair value from
  manual valuation snapshots.
- Traceability anchors preserve backward-compatible identifier lists and also
  expose typed `details` rows. Each detail row identifies the anchor kind,
  source id/type, amount contribution when available, currency, review state,
  confidence tier, and contribution basis. `JournalEntry.source_id` is never
  assumed to be a statement transaction; it must resolve to a user-owned typed
  record before it can support a trusted source anchor.
- Unknown journal source ids are explicit package blockers through
  `unknown_source_anchor`. They may appear as `unknown_source:<uuid>` for
  debugging, but they must not be emitted as `statement_transaction:<uuid>`.
- Non-ledger disclosures, such as the non-compliance statement, use
  `ledger_anchor.state=not_applicable`.
- The representative package proof fixture must pin Decimal expected outputs
  for bank cash, brokerage market value, dividend income, market price
  freshness, manual property/liability values, restricted holdings, notes, and
  traceability identifiers. Package E2E assertions consume those expected
  outputs from the shared fixture contract rather than recalculating independent
  constants inline.

Completeness warning taxonomy:

| Code | Purpose |
|---|---|
| `missing_source_anchor` | Trusted totals cannot be treated as auditable until a source anchor or explicit manual input exists |
| `manual_only_source` | Manual valuation rows require visible manual snapshot identifiers and basis |
| `stale_market_data` | Investment values require freshness disclosure or refreshed provider data |
| `duplicate_source_coverage` | Duplicate source coverage must be excluded or reviewed before totals are trusted |
| `overlapping_statement_period` | Overlapping period coverage requires review before period totals are trusted |
| `unknown_source_anchor` | Journal source IDs must resolve to typed source records before supporting trusted totals |

Export contract:

- Formats: `json`, `csv`
- CSV columns: `package_id`, `section_id`, `line_id`, `label`, `amount`,
  `currency`, `source_state`, `selected_framework_id`,
  `framework_policy_result_id`, `framework_policy_matrix_version`, and
  `evidence_bundle_references`.
- Export metadata displayed by the package UI must include the selected
  framework, policy result ID, matrix version, and evidence anchor references
  from the policy result.
- The package UI exposes an authenticated CSV download after framework
  selection. It calls `GET /api/reports/export?report_type=package&format=csv&framework_id={selected_framework_id}`
  through the shared API download helper.
- Decimal fields must serialize as strings so frontend, CSV export, and E2E
  assertions do not lose money precision.

---

## 3. Multi-Currency Consolidation

### Base Currency
Reports are generated in a single base currency (user configurable, default: SGD).

### FX Rate Application
- Use **period-end rate** for balance sheet items
- Use **average rate** for income statement items
- Record calculated unrealized FX gains/losses separately
- Use the requested balance sheet `as_of_date` for manual valuation snapshots.
- For portfolio market valuation adjustments, historical balance sheets remain date-bounded to the requested `as_of_date`; the current-day balance sheet uses the latest imported brokerage snapshot when provider output normalizes a current statement to a future period end.
- Return `fx_warnings` when an average-rate calculation falls back to a spot rate
- When an FX rate is unavailable after allowed fallback/lazy-resolution
  attempts, the affected currency is excluded from converted trusted totals and
  the report returns an explicit partial warning such as
  `missing_fx_rate_partial_skip` or `missing_fx_revaluation_partial_skip`.
  Reports must never silently assume a 1:1 rate for a foreign currency.
- Core report pages must render non-empty `fx_warnings` visibly before the
  headline KPI/cards so users can see that totals are partial or fallback-based.
- The Balance Sheet page must render equation component detail for
  `net_income`, `unrealized_fx_gain_loss`,
  `net_worth_adjustment_gain_loss`, and `equation_delta`.

```python
from src.money import ExchangeRate, Money, convert, to_money

def consolidate_amount(amount: Decimal, currency: str, target: str, date: date) -> Decimal:
    if currency == target:
        return to_money(amount)
    rate = get_fx_rate(currency, target, date)
    return convert(Money(amount, currency), ExchangeRate(currency, target, rate)).amount
```

### Balance Sheet Net Worth Sources

The balance sheet combines three source classes:

| Source | Rule |
|--------|------|
| Journal lines | Aggregate posted/reconciled asset, liability, and equity account balances through the report date |
| Active portfolio positions | Add a market valuation adjustment per broker account equal to `current market value - ledger-backed position cost basis`; current-day reports may use the latest imported brokerage snapshot date to match `/portfolio/holdings` |
| Manual valuation snapshots | Add latest in-scope asset/liability snapshots from `/assets/valuation-components` as synthetic report lines; restricted retirement/benefit assets contribute when `include_restricted=true` |

Portfolio adjustments prevent double counting without removing broker cash. If position cost basis already exists as a debit to the broker account, only the market-value delta is added to assets. If no cost-basis journal exists, the full market value is added.

Manual valuation snapshots use `include_in_total_net_worth` to decide balance sheet inclusion. Snapshot currency is converted to the report currency using the historical FX rate on the report `as_of_date`.

Balance sheet source classes also carry report-line provenance: ledger account
lines derive provenance from contributing journal source types, active portfolio
market adjustments are `derived`, and manual valuation snapshot synthetic lines
are `manual`.

`unrealized_fx_gain_loss` is not a balancing plug. It is calculated from foreign-currency asset/liability accounts by comparing:

```
native account balance * report-date spot rate
  - historical base-currency cost from posted/reconciled non-revaluation journal lines
```

Posted `FX_REVALUATION` journal entries are excluded from both native balance and historical cost calculations so a prior revaluation does not change the next period's nominal foreign-currency balance.

`net_worth_adjustment_gain_loss` is the explicit balancing component for non-ledger value included by portfolio market adjustments and manual valuation snapshots. It is computed from those added report lines, not from the remaining balance sheet delta.

### <a id="internal-transfer-net-worth-neutrality"></a>Internal-Transfer Net-Worth Neutrality

**Generalized invariant.** Net worth changes only via **external in/out** (real
income / expense), **market moves** (portfolio valuation), and **FX revaluation**.
**Internal (own-account) transfers cancel** — they move money between the owner's
own accounts and must not change net worth.

A matched cross-currency transfer (see
[FX / Cross-Currency Transfer Pairing](reconciliation.md#fx-cross-currency-transfer-pairing))
is therefore classified **net-zero** (#1123 AC3): the transfer-**in** leg is *not*
income and the matching transfer-**out** leg is *not* expense. The only net-worth
impact is the transfer **fee**, which is a real external outflow. Implemented by
`classify_internal_transfer` (`services/fx_transfer.py`): `net_worth_delta = −fee`
for an internal transfer, `income − expense` otherwise.

This classification is **wired into report generation** (#1123 AC3, live):
`reporting._internal_transfer_adjustment` loads recorded `fx_conversions` rows
whose legs are anchored to journal entries (`from_journal_entry_id` /
`to_journal_entry_id`), re-validates each through `pair_fx_legs` +
`classify_internal_transfer`, and excludes the matched legs from the income /
expense aggregation in both `generate_income_statement` and the cumulative
balance-sheet net income — adding back only the (converted) fee. A naively
double-booked internal transfer therefore nets to zero in the report except for
its fee, proven end to end in `reporting/test_internal_transfer_e2e.py`.

**Source: recorded rows OR raw ledger (#1123 AC2 live).** The adjustment does not
require a pre-seeded `fx_conversions` row. In addition to recorded rows, it calls
`services/fx_transfer_discovery.discover_fx_conversions` to **auto-discover** the
same transfer pairs directly from the raw `ASSET`-account journal lines (see
[FX / Cross-Currency Transfer Pairing](reconciliation.md#fx-cross-currency-transfer-pairing)).
Discovered (in-memory) conversions are merged with recorded ones and deduplicated
by the unordered pair of anchored journal entries, so a transfer that is BOTH
recorded and discoverable is never netted twice. A cross-currency internal
transfer booked purely as raw ledger lines is therefore net-worth-correct end to
end with **no manual conversion row**, proven in
`reporting/test_fx_ledger_autodiscovery_e2e.py`. Discovery is conservative — only
unambiguous 1:1 matches net, so the report biases toward *under*-netting and skips
ambiguous matches — reducing, though not fully eliminating, false-positive netting
without an explicit linkage signal.

**FX gain/loss is attributed to revaluation over time, not the conversion event**
(#1123 AC4). A same-day round-trip conversion A→B→A nets ~zero realized P&L (minus
fee/spread) because the market rate has not moved
(`round_trip_realized_pnl == −fee`). Any later divergence between the recorded
conversion and a subsequent valuation is a holding-period **revaluation**, routed
through the `FX_REVALUATION` journal source type (consistent with
`unrealized_fx_gain_loss` above) — never booked as a conversion-event
income/expense line. This is also proven **live through the real report**: a
same-day SGD→USD→SGD round-trip seeded as raw ledger lines is auto-discovered,
both legs net out, and `generate_income_statement` returns zero realized P&L
(`reporting/test_fx_ledger_autodiscovery_e2e.py::test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report`).

---

## 4. Design Constraints

### ✅ Recommended Patterns
- **Pattern A**: Report generation is read-only, never modifies ledger
- **Pattern B**: Always validate accounting equation before rendering
- **Pattern C**: Cache report results with date-based invalidation
- **Pattern D (Performance)**: Pre-fetch all necessary FX rates in bulk before starting report calculation to avoid N+1 queries.
- **Pattern E (Reliability)**: Cap trend data points at 366 (one year of daily data) to prevent memory issues with unbounded queries.
- **Pattern F**: Include market valuation deltas, not full portfolio values, when the account already has ledger cost basis.
- **Pattern G**: Calculate unrealized FX from historical cost; never use the accounting equation remainder as FX.
- **Pattern H**: Missing FX data produces an explicit partial report warning and excludes the unconvertible currency from trusted converted totals.

### ⛔ Prohibited Patterns
- **Anti-pattern A**: **NEVER** hardcode account codes in report logic
- **Anti-pattern B**: **NEVER** silently generate converted totals for foreign-currency data without a real FX rate or explicit partial warning
- **Anti-pattern C**: **NEVER** double count a broker account by adding both its ledger cost and full market value.
- **Anti-pattern D**: **NEVER** let posted `FX_REVALUATION` entries change native foreign-currency balances.

---

## 5. Verification

| Behavior | Test Method | Status |
|----------|-------------|--------|
| Balance sheet balances | `test_balance_sheet_equation` | ✅ Implemented |
| Income statement period | `test_income_statement_calculation` | ✅ Implemented |
| Multi-currency consolidation | `test_fx_consolidation` | ⏳ Pending |
| Calculated unrealized FX | `test_reporting_fx_revaluation_integration.py` | ✅ Implemented |
| Average-rate fallback warnings | `test_reporting_fx_revaluation_integration.py` | ✅ Implemented |
| Portfolio market value adjustments | `test_reporting_net_worth_components.py` | ✅ Implemented |
| Manual valuation snapshots | `test_reporting_net_worth_components.py` | ✅ Implemented |
| Account trend | `test_account_trend_monthly` | ✅ Implemented |
| Net worth time-series | `test_net_worth_timeseries_daily_points` | ✅ Implemented |
| Net worth historical FX | `test_net_worth_timeseries_uses_historical_fx_per_point` | ✅ Implemented |
| Category breakdown | `test_category_breakdown_quarterly` | ✅ Implemented |
| Cash flow statement | `test_cash_flow_statement` | ✅ Implemented |
| Tag filtering | `test_income_statement_with_tags_filter` | ✅ Implemented |
| Account type filtering | `test_income_statement_with_account_type_filter` | ✅ Implemented |

---

## Used by

- [schema.md](./schema.md)
- [accounting.md](./accounting.md)
