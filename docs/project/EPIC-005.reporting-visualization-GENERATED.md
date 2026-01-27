# EPIC-005: Financial Reports & Visualization — GENERATED

> **Auto-generated implementation summary** — Do not edit manually.
> **Last updated**: 2026-01-27
> **Source EPIC**: [EPIC-005.reporting-visualization.md](./EPIC-005.reporting-visualization.md)

---

## 📋 Implementation Summary

EPIC-005 delivers standard financial statements (balance sheet, income statement, cash flow statement), visualization components, and data export capabilities. The implementation uses ECharts for all chart types and supports multi-currency reporting with SGD as the base currency.

### Completed Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| Balance Sheet API | `apps/backend/src/routers/reports.py` | ✅ Complete |
| Income Statement API | `apps/backend/src/routers/reports.py` | ✅ Complete |
| Cash Flow Statement API | `apps/backend/src/routers/reports.py` | ✅ Complete |
| Trend Data API | `apps/backend/src/routers/reports.py` | ✅ Complete |
| Category Breakdown API | `apps/backend/src/routers/reports.py` | ✅ Complete |
| Export API (CSV/PDF) | `apps/backend/src/routers/reports.py` | ✅ Complete |
| Reporting Service | `apps/backend/src/services/reporting.py` | ✅ Complete |
| FX Service | `apps/backend/src/services/fx.py` | ✅ Complete |
| Dashboard Page | `apps/frontend/src/app/dashboard/page.tsx` | ✅ Complete |
| Balance Sheet Page | `apps/frontend/src/app/reports/balance-sheet/page.tsx` | ✅ Complete |
| Income Statement Page | `apps/frontend/src/app/reports/income-statement/page.tsx` | ✅ Complete |
| TrendChart Component | `apps/frontend/src/components/charts/TrendChart.tsx` | ✅ Complete |
| PieChart Component | `apps/frontend/src/components/charts/PieChart.tsx` | ✅ Complete |
| BarChart Component | `apps/frontend/src/components/charts/BarChart.tsx` | ✅ Complete |
| SankeyChart Component | `apps/frontend/src/components/charts/SankeyChart.tsx` | ✅ Complete |

---

## 🏗️ Architecture Decisions

### 1. Chart Library Selection: ECharts

**Decision**: Standardize on ECharts for all chart types.

**Rationale**:
- Rich financial chart support (K-line, Candlestick, Sankey)
- Superior performance with large datasets (Canvas rendering)
- Consistent styling across all chart types
- Good React integration via `echarts-for-react`

**Implementation**:
```typescript
// Load ECharts sub-modules on demand to reduce bundle size
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart, SankeyChart } from 'echarts/charts';
```

### 2. Base Currency: SGD

**Decision**: Use SGD as the default base currency for all reports.

**Rationale**:
- User base is primarily in Singapore
- Consistent with SSOT requirements
- Exchange rate conversion handled at report generation time

### 3. Exchange Rate Data Source: Yahoo Finance

**Decision**: Use Yahoo Finance API (free) for exchange rate data.

**Rationale**:
- Free tier sufficient for personal use
- Reliable data quality
- Easy integration via `yfinance` library
- Daily rate caching (24-hour TTL in Redis)

### 4. Report Period Definition: Calendar Month

**Decision**: Use calendar month (1st-31st) for all period-based reports.

**Rationale**:
- Most intuitive for users
- Aligns with bank statement periods
- Database query optimization: `DATE_TRUNC('month', entry_date)`

---

## 📁 Backend Implementation

### Services

#### `services/reporting.py`

```python
# Core functions implemented
async def generate_balance_sheet(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date,
    currency: str = "SGD"
) -> BalanceSheetResponse:
    """
    Generate balance sheet as of a specific date.
    Verifies: Assets = Liabilities + Equity
    """

async def generate_income_statement(
    db: AsyncSession,
    user_id: UUID,
    start_date: date,
    end_date: date,
    currency: str = "SGD"
) -> IncomeStatementResponse:
    """
    Generate income statement for a date range.
    Calculates: Net Income = Total Income - Total Expenses
    """

async def generate_cash_flow(
    db: AsyncSession,
    user_id: UUID,
    start_date: date,
    end_date: date,
    currency: str = "SGD"
) -> CashFlowResponse:
    """
    Generate cash flow statement.
    Classifies activities: Operating, Investing, Financing
    """

async def get_account_trend(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    period: str = "monthly"  # daily|weekly|monthly
) -> list[TrendDataPoint]:
    """Get historical balance trend for an account."""

async def get_category_breakdown(
    db: AsyncSession,
    user_id: UUID,
    account_type: str,  # income|expense
    period: str
) -> list[CategoryBreakdown]:
    """Get breakdown by category for pie charts."""
```

#### `services/fx.py`

```python
async def get_exchange_rate(
    from_currency: str,
    to_currency: str,
    as_of_date: date | None = None
) -> Decimal:
    """
    Get exchange rate with Redis caching.
    Falls back to last known rate if API unavailable.
    """

async def convert_to_base(
    amount: Decimal,
    from_currency: str,
    to_currency: str = "SGD",
    fx_rate: Decimal | None = None
) -> Decimal:
    """Convert amount to base currency."""
```

### API Endpoints

| Endpoint | Method | Parameters | Response |
|----------|--------|------------|----------|
| `/api/reports/balance-sheet` | GET | `as_of_date`, `currency` | Balance sheet with asset/liability/equity totals |
| `/api/reports/income-statement` | GET | `start_date`, `end_date`, `currency` | Income statement with category breakdown |
| `/api/reports/cash-flow` | GET | `start_date`, `end_date`, `currency` | Cash flow by activity type |
| `/api/reports/trend` | GET | `account_id`, `period` | Historical balance data points |
| `/api/reports/breakdown` | GET | `type`, `period` | Category breakdown for pie charts |
| `/api/reports/export` | GET | `report_type`, `format`, `...params` | CSV or PDF download |

---

## 📁 Frontend Implementation

### Dashboard (`/dashboard`)

**Components**:
1. **Asset Overview Cards** — Total assets, total liabilities, net assets
2. **Asset Trend Line Chart** — Last 12 months balance trend (ECharts)
3. **Income/Expense Bar Chart** — Monthly comparison (ECharts)
4. **Account Distribution Pie Chart** — By account type (ECharts)
5. **Recent Transactions List** — Last 10 transactions
6. **Unmatched Alerts** — Count of unmatched statement transactions

### Report Pages

#### Balance Sheet (`/reports/balance-sheet`)

**Layout**: Three-column layout (Assets | Liabilities | Equity)

**Features**:
- Account hierarchy with expand/collapse
- Date picker for historical reports
- Export button (CSV/PDF)
- Currency switcher

#### Income Statement (`/reports/income-statement`)

**Layout**: Income categories → Expense categories → Net Income

**Features**:
- Year-over-year comparison
- Time range selection
- Tag filtering
- Account type filtering

#### Cash Flow (`/reports/cash-flow`)

**Layout**: Sankey diagram showing cash flow between categories

**Features**:
- Operating/Investing/Financing classification
- Interactive flow visualization

### Chart Components

All chart components follow the pattern:

```typescript
interface ChartProps {
  data: ChartData[];
  title?: string;
  height?: number;
  loading?: boolean;
  onDataPointClick?: (item: ChartData) => void;
}

export function TrendChart({ data, title, height = 300, loading }: ChartProps) {
  const option = useMemo(() => ({
    // ECharts configuration
  }), [data]);

  if (loading) return <Skeleton height={height} />;
  return <ReactECharts option={option} style={{ height }} />;
}
```

---

## 🧪 Test Coverage

### Report Calculation Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_balance_sheet_equation` | Assets = Liabilities + Equity | ✅ Pass |
| `test_income_statement_calculation` | Net Income = Income - Expenses | ✅ Pass |
| `test_report_matches_journal` | Report amounts match journal entry totals | ✅ Pass |

### Multi-Currency Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_multi_currency_conversion` | Correct FX conversion (SGD + USD) | ✅ Pass |
| `test_fx_rate_update` | Reports recalculate after rate update | ✅ Pass |

### Performance Tests

| Test | Description | Status |
|------|-------------|--------|
| `test_report_generation_performance` | 1 year data < 2s | ✅ Pass |

---

## 📏 Acceptance Criteria Status

### 🟢 Must Have

| Criterion | Status | Verification |
|-----------|--------|--------------|
| Balance sheet balanced | ✅ | Assets = Liabilities + Equity within 0.01 tolerance |
| Income statement correct | ✅ | Manual verification of 5 months data |
| Reports consistent with journal | ✅ | Report amounts traceable to journal entries |
| Report generation < 2s | ✅ | Performance test passed |
| Mobile responsive | ✅ | Responsive layout implemented |
| Data export functional | ✅ | Excel/CSV download working |

### 🌟 Nice to Have

| Criterion | Status | Notes |
|-----------|--------|-------|
| Report caching (Redis) | ⏳ | Planned for v1.5 |
| Chart interactions (drill-down) | ⏳ | Click to view details pending |
| Budget comparison | ⏳ | Planned for v2.0 |
| Custom reports | ⏳ | Planned for v2.0 |
| Scheduled report emails | ⏳ | Planned for v2.0 |

---

## 📝 Technical Debt

| Item | Priority | Status |
|------|----------|--------|
| Unrealized FX Gain/Loss | P2 | Pending — Track FX gains/losses separately per SSOT |
| Report materialized views | P2 | Pending — Performance optimization phase |
| Budget management | P3 | Planned for v2.0 |
| Custom reports | P3 | Planned for v2.0 |

---

## 🔗 SSOT References

- [schema.md](../ssot/schema.md) — Account and journal entry tables
- [reporting.md](../ssot/reporting.md) — Report calculation rules
- [market_data.md](../ssot/market_data.md) — Exchange rate data source

---

## ✅ Verification Commands

```bash
# Run report calculation tests
moon run backend:test -- -k "test_balance_sheet" -v

# Verify API endpoints
curl "http://localhost:8000/api/reports/balance-sheet?as_of_date=2025-12-31" \
  -H "X-User-Id: <uuid>"

curl "http://localhost:8000/api/reports/income-statement?start_date=2025-01-01&end_date=2025-12-31" \
  -H "X-User-Id: <uuid>"

# Verify dashboard loads
open http://localhost:3000/dashboard

# Verify report pages
open http://localhost:3000/reports/balance-sheet
open http://localhost:3000/reports/income-statement
```

---

*This file is auto-generated from EPIC-005 implementation. For goals and acceptance criteria, see [EPIC-005.reporting-visualization.md](./EPIC-005.reporting-visualization.md).*
