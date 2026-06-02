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
| `data_freshness` | Latest price date, market-data provider, stale flag, and manual override basis |
| `source_links` | Brokerage statement/import IDs, price source IDs, ledger entry IDs, and report anchors needed for source-to-ledger-to-report traceability |
| `notes` | Methods and limitations for cost basis, price freshness, dividends, XIRR/TWR/MWR, and any manual overrides |

The schedule must not mutate ledger state. It assembles existing portfolio,
market-data, dividend, and journal-entry facts into a reporting payload that can
be exported or embedded by EPIC-005.

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
