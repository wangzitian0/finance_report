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

Package readiness:

- Endpoint: `GET /api/reports/package/readiness`
- Owner: EPIC-019 Slice 5 (#639).
- Purpose: return the user-scoped readiness state and blocker links before the
  report package renders output. This endpoint is the package-owned fact source;
  workflow summary APIs may aggregate it but must not duplicate its derivation.
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
def consolidate_amount(amount: Decimal, currency: str, target: str, date: date) -> Decimal:
    if currency == target:
        return amount
    rate = get_fx_rate(currency, target, date)
    return (amount * rate).quantize(Decimal("0.01"))
```

### Balance Sheet Net Worth Sources

The balance sheet combines three source classes:

| Source | Rule |
|--------|------|
| Journal lines | Aggregate posted/reconciled asset, liability, and equity account balances through the report date |
| Active portfolio positions | Add a market valuation adjustment per broker account equal to `current market value - ledger-backed position cost basis`; current-day reports may use the latest imported brokerage snapshot date to match `/portfolio/holdings` |
| Manual valuation snapshots | Add latest in-scope asset/liability snapshots from `/assets/valuation-components` as synthetic report lines |

Portfolio adjustments prevent double counting without removing broker cash. If position cost basis already exists as a debit to the broker account, only the market-value delta is added to assets. If no cost-basis journal exists, the full market value is added.

Manual valuation snapshots use `include_in_total_net_worth` to decide balance sheet inclusion. Snapshot currency is converted to the report currency using the historical FX rate on the report `as_of_date`.

`unrealized_fx_gain_loss` is not a balancing plug. It is calculated from foreign-currency asset/liability accounts by comparing:

```
native account balance * report-date spot rate
  - historical base-currency cost from posted/reconciled non-revaluation journal lines
```

Posted `FX_REVALUATION` journal entries are excluded from both native balance and historical cost calculations so a prior revaluation does not change the next period's nominal foreign-currency balance.

`net_worth_adjustment_gain_loss` is the explicit balancing component for non-ledger value included by portfolio market adjustments and manual valuation snapshots. It is computed from those added report lines, not from the remaining balance sheet delta.

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
