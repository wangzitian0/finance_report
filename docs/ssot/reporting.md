# Financial Reporting (Source of Truth)

> **SSOT Key**: `reporting`
> **Purpose**: Financial report generation logic, report types, and calculation rules.

---

## 1. Source of Truth

### Physical File Locations

| File | Purpose |
|------|---------|
| `apps/backend/src/services/reporting.py` | Core report generation logic |
| `apps/backend/src/services/reporting_snapshot.py` | Report caching and snapshots |
| `apps/backend/src/routers/reports.py` | Report API endpoints |
| `apps/frontend/app/(main)/reports/` | Report pages and layouts |
| `apps/frontend/components/charts/` | Chart components |

---

## 2. Architecture Model

### Report Types

#### Balance Sheet (Statement of Financial Position)

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

**Validation**: `Total Assets = Total Liabilities + Total Equity`

#### Income Statement (Profit & Loss)

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

#### Cash Flow Statement

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

### Multi-Currency Consolidation

#### Base Currency

Reports are generated in a single base currency (user configurable, default: SGD).

#### FX Rate Application

- Use **period-end rate** for balance sheet items
- Use **average rate** for income statement items
- Record unrealized FX gains/losses separately

```python
def consolidate_amount(amount: Decimal, currency: str, target: str, date: date) -> Decimal:
    if currency == target:
        return amount
    rate = get_fx_rate(currency, target, date)
    return (amount * rate).quantize(Decimal("0.01"))
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/reports/balance-sheet` | Balance sheet as of date |
| GET | `/api/reports/income-statement` | Income statement for period |
| GET | `/api/reports/cash-flow` | Cash flow statement for period |
| GET | `/api/reports/trend` | Account balance trend over time |
| GET | `/api/reports/category-breakdown` | Breakdown by category |

---

## 3. Design Constraints

### Recommended Patterns

| Pattern | Description |
|---------|-------------|
| **Read-Only** | Report generation never modifies ledger |
| **Equation Validation** | Always validate accounting equation before rendering |
| **Date-Based Cache** | Cache report results with date-based invalidation |
| **Bulk FX Fetch** | Pre-fetch all necessary FX rates in bulk to avoid N+1 queries |
| **Trend Data Cap** | Cap trend data points at 366 (one year daily) to prevent memory issues |

### Hard Rules

| Rule | Description |
|------|-------------|
| **No Hardcoded Codes** | **NEVER** hardcode account codes in report logic |
| **FX Required** | **NEVER** generate reports without FX rate data |
| **Decimal Precision** | All amounts use `Decimal` with 2 decimal places |
| **Equation Must Hold** | Balance sheet must satisfy `Assets = Liabilities + Equity` |

### Prohibited Patterns

- Hardcoding account codes in report logic
- Generating reports without FX rate data for multi-currency accounts
- Using `float` for monetary calculations

---

## 4. Playbooks (SOP)

### Generate Balance Sheet

```bash
# API call for balance sheet as of specific date
curl "http://localhost:8000/api/reports/balance-sheet?as_of=2026-01-27" \
  -H "X-User-Id: <user-uuid>"
```

### Generate Income Statement

```bash
# API call for income statement over period
curl "http://localhost:8000/api/reports/income-statement?start_date=2026-01-01&end_date=2026-01-31" \
  -H "X-User-Id: <user-uuid>"
```

### Generate Account Trend

```bash
# Get monthly trend for an account
curl "http://localhost:8000/api/reports/trend?account_id=<account-uuid>&period=monthly&start_date=2025-01-01&end_date=2026-01-01" \
  -H "X-User-Id: <user-uuid>"
```

### Filter by Tags

```bash
# Income statement filtered by tags
curl "http://localhost:8000/api/reports/income-statement?start_date=2026-01-01&end_date=2026-01-31&tags=business,travel" \
  -H "X-User-Id: <user-uuid>"
```

### Debugging Report Issues

1. **Balance Sheet Doesn't Balance**
   - Check for orphaned journal lines
   - Verify all entries have balanced debits/credits
   - Run accounting equation check

2. **Missing FX Rates**
   - Check `fx_rates` table for required currency pairs and dates
   - Verify FX sync job is running
   - Use fallback rate if historical rate unavailable

3. **Trend Data Empty**
   - Verify journal entries exist in the date range
   - Check account_id is valid
   - Ensure period parameter is valid (daily, weekly, monthly, quarterly)

---

## 5. Verification (The Proof)

### Test Coverage

| Behavior | Test Method | Status |
|----------|-------------|--------|
| Balance sheet balances | `test_balance_sheet_equation` | ✅ Implemented |
| Income statement period | `test_income_statement_calculation` | ✅ Implemented |
| Multi-currency consolidation | `test_fx_consolidation` | ⏳ Pending |
| Account trend | `test_account_trend_monthly` | ✅ Implemented |
| Category breakdown | `test_category_breakdown_quarterly` | ✅ Implemented |
| Cash flow statement | `test_cash_flow_statement` | ✅ Implemented |
| Tag filtering | `test_income_statement_with_tags_filter` | ✅ Implemented |
| Account type filtering | `test_income_statement_with_account_type_filter` | ✅ Implemented |

### Run Report Tests

```bash
# Run all reporting tests
moon run backend:test -- -k reporting

# Run with coverage
moon run backend:test -- -k reporting --cov=src/services/reporting
```

### API Verification

```bash
# Verify balance sheet endpoint
curl -s "http://localhost:8000/api/reports/balance-sheet" \
  -H "X-User-Id: <user-uuid>" | jq '.total_assets, .total_liabilities_equity'

# Expected: total_assets == total_liabilities_equity
```

### Equation Check

```bash
# Quick balance check via Python
uv run python -c "
from src.services.reporting import validate_accounting_equation
result = validate_accounting_equation(user_id='<user-uuid>')
print('Equation valid:', result)
"
```

---

## Used by

- [schema.md](./schema.md) — Database models for accounts and journal entries
- [accounting.md](./accounting.md) — Double-entry bookkeeping rules
- [market_data.md](./market_data.md) — FX rates for multi-currency consolidation

---

*Last updated: 2026-01-27*
