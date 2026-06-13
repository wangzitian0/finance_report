---
name: reporting
description: Financial report generation including balance sheet, income statement, and cash flow. Use this skill when working with financial reports, multi-currency consolidation, or report calculations.
---

# Financial Reporting

> **Core Definition**: Financial report generation logic, report types, and calculation rules.
> **SSOT**: [`docs/ssot/reporting.md`](../../../../docs/ssot/reporting.md) is authoritative.

## Report Types

### Balance Sheet
Shows assets, liabilities, and equity at a point in time.
- **Validation**: `Total Assets = Total Liabilities + Total Equity`

#### Three net-worth source classes

| Source | Rule |
|--------|------|
| Journal lines | Aggregate posted/reconciled asset/liability/equity balances through the report date |
| Active portfolio positions | Add a per-broker market-value **adjustment** = `current market value − ledger-backed cost basis` (only the delta, to avoid double counting) |
| Manual valuation snapshots | Add latest in-scope `manual_valuation_snapshots` as synthetic report lines (EPIC-011), gated by `include_in_total_net_worth` |

- `net_worth_adjustment_gain_loss` is the **explicit balancing component** for
  non-ledger value (portfolio adjustments + manual valuations). Compute it from
  those added report lines, **not** from the remaining balance-sheet delta.
- `unrealized_fx_gain_loss` is **not a plug**. Compute as
  `native balance × report-date spot − historical base-currency cost from
  posted/reconciled non-revaluation lines`. Posted `FX_REVALUATION` entries are
  **excluded** from both native balance and historical cost.

#### Restricted-liquidity toggle (EPIC-011)

Restricted holdings are excluded by default. `/reports/balance-sheet` and the
Balance Sheet page MUST default `include_restricted=false`. Manual valuations
carry a `liquidity_class` (LIQUID / RESTRICTED / ILLIQUID / LIABILITY).

### Income Statement (P&L)
Shows income and expenses over a period.
- **Calculation**: `Net Income = Total Income - Total Expenses`

### Cash Flow Statement
Shows cash movements by category:
- Operating Activities
- Investing Activities
- Financing Activities

## Multi-Currency Consolidation

- **Base Currency**: User configurable (default: SGD)
- **Balance Sheet**: Use period-end FX rate
- **Income Statement**: Use trailing/average FX rate
- Round through the canonical helper `to_money()` (banker's rounding,
  `ROUND_HALF_EVEN`) — see [`accounting`](../accounting/SKILL.md) Rule A2. Do NOT
  hand-roll `quantize(Decimal("0.01"))` without the canonical mode.

```python
from src.utils import to_money

def consolidate_amount(amount: Decimal, currency: str, target: str, date: date) -> Decimal:
    if currency == target:
        return amount
    rate = get_fx_rate(currency, target, date)
    return to_money(amount * rate)
```

## Annualized Income Schedule (EPIC-011)

- Endpoint: `GET /api/reports/package/annualized-income-schedule`
- Trailing **365 days** ending at `as_of_date` (defaults to request date).
- Buckets posted/reconciled income lines into salary / bonus / dividend / total.
- Convert each line to the schedule currency **before** aggregation (trailing
  average FX for the window); NEVER add mixed-currency nominals raw.
- Restricted-comp basis: latest as-of snapshots for `esop`/`rsu`/`stock_options`
  with `liquidity_class=restricted`.

## Notes & Disclosures

- Endpoint: `GET /api/reports/package/notes`. Required IDs: `basis-of-preparation`,
  `reporting-period-and-currency`, `valuation-basis` (EPIC-011),
  `investment-market-data`, `source-confidence-review`, `restricted-asset-treatment`.
- The package non-compliance statement must state the report is not a regulated
  filing, audit opinion, legal, or tax advice.

## Design Constraints

### Recommended Patterns
- Report generation is read-only, never modifies ledger
- Always validate accounting equation before rendering
- Cache report results with date-based invalidation
- Pre-fetch all FX rates in bulk to avoid N+1 queries
- Cap trend data points at 366 to prevent memory issues

### Prohibited Patterns
- **NEVER** hardcode account codes in report logic
- **NEVER** generate reports without FX rate data

## Source Files

- **Logic**: `apps/backend/src/services/reporting.py`
- **Templates**: `apps/frontend/src/app/reports/`
- **Charts**: `apps/frontend/src/components/charts/`
