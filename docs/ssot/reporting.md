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

### 2.6 Personal Financial-Report Package Contract

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
| `period_semantics` | Defines required `start_date`, `end_date`, `as_of_date`, `currency`, and `decimal_serialization` semantics |
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

Annualized income and long-term compensation schedule:

- Endpoint: `GET /api/reports/package/annualized-income-schedule`
- Period semantics: trailing 365 days ending at `as_of_date`; when omitted,
  `as_of_date` defaults to the request date.
- Income basis: `POSTED` or `RECONCILED` income journal lines in the trailing
  period, bucketed into salary, bonus, dividend, and total by income account
  name.
- Restricted compensation basis: latest as-of manual valuation snapshots for
  `esop`, `rsu`, and `stock_options` with `liquidity_class=restricted`.
- Liquid net worth default: restricted holdings are excluded by default and are
  only included through the balance-sheet restricted toggle.
- Decimal fields serialize as strings; restricted fair-value totals are reported
  in the schedule currency and do not imply cross-currency conversion.

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
- Trusted package totals must expose source and ledger anchors unless the line
  is an explicit manual input, such as restricted compensation fair value from
  manual valuation snapshots.
- Non-ledger disclosures, such as the non-compliance statement, use
  `ledger_anchor.state=not_applicable`.

Completeness warning taxonomy:

| Code | Purpose |
|---|---|
| `missing_source_anchor` | Trusted totals cannot be treated as auditable until a source anchor or explicit manual input exists |
| `manual_only_source` | Manual valuation rows require visible manual snapshot identifiers and basis |
| `stale_market_data` | Investment values require freshness disclosure or refreshed provider data |
| `duplicate_source_coverage` | Duplicate source coverage must be excluded or reviewed before totals are trusted |
| `overlapping_statement_period` | Overlapping period coverage requires review before period totals are trusted |

Export contract:

- Formats: `json`, `csv`
- CSV columns: `package_id`, `section_id`, `line_id`, `label`, `amount`,
  `currency`, `source_state`
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

### ⛔ Prohibited Patterns
- **Anti-pattern A**: **NEVER** hardcode account codes in report logic
- **Anti-pattern B**: **NEVER** generate reports without FX rate data
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
