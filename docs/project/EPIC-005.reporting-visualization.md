# EPIC-005: Financial Reports & Visualization

> **Status**: ⏳ Pending  
> **Phase**: 4  
> **Duration**: 3 weeks  
> **Dependencies**: EPIC-002 (can be parallel with EPIC-003/004)  

---

## 🎯 Objective

Generate standard financial statements (balance sheet, income statement, cash flow statement), visualize asset structure and trends, and help users comprehensively understand their financial status.

**Core Constraints**:
```
Balance Sheet: Assets = Liabilities + Equity
Income Statement: Net Income = Income - Expenses
Accounting Equation Verification: Reports must comply with accounting equation
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 📊 **Accountant** | Report accuracy | Three statements must comply with accounting standards, data sources must be traceable |
| 🏗️ **Architect** | Computation performance | Large data volume reports need caching or materialized views |
| 💻 **Developer** | Chart implementation | Recharts for lightweight scenarios, ECharts for complex charts |
| 📋 **PM** | User understanding | Reports need explanations and examples, understandable for non-accounting users |
| 🧪 **Tester** | Calculation verification | Compare with manual calculations, error < 1% |

---

## ✅ Task Checklist

### Report Calculation (Backend)

- [ ] `services/reporting.py` - Report generation service
  - [ ] `generate_balance_sheet()` - Balance sheet
    - Aggregate balances by account type
    - Verify Assets = Liabilities + Equity
  - [ ] `generate_income_statement()` - Income statement
    - Income/expense details
    - Monthly/quarterly/annual comparison
  - [ ] `generate_cash_flow()` - Cash flow statement (P2)
    - Classify operating/investing/financing activities
  - [ ] `get_account_trend()` - Account trend data
  - [ ] `get_category_breakdown()` - Category breakdown

### Multi-Currency Handling (Backend)

- [ ] `services/fx.py` - Exchange rate service
  - [ ] `get_exchange_rate()` - Get exchange rate
  - [ ] `convert_to_base()` - Convert to base currency
  - [ ] Exchange rate caching (daily update)
- [ ] Report currency configuration
  - [ ] Base currency setting (default SGD)
  - [ ] Unified report conversion

### API Endpoints (Backend)

- [ ] `GET /api/reports/balance-sheet` - Balance sheet
  - Parameters: `as_of_date`, `currency`
- [ ] `GET /api/reports/income-statement` - Income statement
  - Parameters: `start_date`, `end_date`, `currency`
- [ ] `GET /api/reports/cash-flow` - Cash flow statement (P2)
- [ ] `GET /api/reports/trend` - Trend data
  - Parameters: `account_id`, `period` (daily/weekly/monthly)
- [ ] `GET /api/reports/breakdown` - Category breakdown
  - Parameters: `type` (income/expense), `period`
- [ ] `GET /api/reports/export` - Export Excel/CSV

### Dashboard (Frontend)

- [ ] `/dashboard` - Home dashboard
  - [ ] Asset overview cards (total assets, total liabilities, net assets)
  - [ ] Asset trend line chart (last 12 months)
  - [ ] Income/expense comparison bar chart (monthly)
  - [ ] Account distribution pie chart (by type)
  - [ ] Recent transactions list
  - [ ] Unmatched alerts

### Report Pages (Frontend)

- [ ] `/reports/balance-sheet` - Balance sheet
  - [ ] Three-column layout (Assets | Liabilities | Equity)
  - [ ] Account hierarchy expand/collapse
  - [ ] Date picker
  - [ ] Export button
- [ ] `/reports/income-statement` - Income statement
  - [ ] Income/expense category details
  - [ ] Year-over-year/month-over-month comparison
  - [ ] Time range selection
- [ ] `/reports/cash-flow` - Cash flow statement (P2)
- [ ] Filters and interactions
  - [ ] Date range
  - [ ] Account type
  - [ ] Currency switching
  - [ ] Tag filtering

### Chart Components (Frontend)

- [ ] `components/charts/TrendChart.tsx` - Trend chart
- [ ] `components/charts/PieChart.tsx` - Pie chart
- [ ] `components/charts/BarChart.tsx` - Bar chart
- [ ] `components/charts/SankeyChart.tsx` - Income/expense flow chart (P2)

---

## 📏 Success Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Balance sheet balanced** | Assets = Liabilities + Equity | 🔴 Critical |
| **Income statement calculation correct** | Manual verification of 5 months data | 🔴 Critical |
| **Reports consistent with journal entries** | Report amounts traceable to journal entries | 🔴 Critical |
| Report generation time < 2s | Performance test (1 year data) | Required |
| Mobile responsive | Responsive layout | Required |
| Data export functional | Excel/CSV download | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Report caching (reduce redundant calculations) | Redis cache hit rate | ⏳ |
| Chart interactions (drill-down) | Click to view details | ⏳ |
| Budget comparison | Actual vs budget | ⏳ |
| Custom reports | User selects dimensions | ⏳ |
| Scheduled report emails | Automatic monthly report | ⏳ |

### 🚫 Not Acceptable Signals

- Balance sheet not balanced
- Report amounts inconsistent with journal entry totals
- Chart data inconsistent with report data
- Performance timeout (> 10s)
- Mobile layout broken

---

## 🧪 Test Scenarios

### Report Calculation Tests (Required)

```python
def test_balance_sheet_equation():
    """Balance sheet: Assets = Liabilities + Equity"""
    report = generate_balance_sheet(as_of_date=date(2025, 12, 31))
    assert abs(report.total_assets - (report.total_liabilities + report.total_equity)) < 0.01

def test_income_statement_calculation():
    """Income statement: Net Income = Income - Expenses"""
    report = generate_income_statement(start=date(2025, 1, 1), end=date(2025, 12, 31))
    assert report.net_income == report.total_income - report.total_expenses

def test_report_matches_journal():
    """Report amounts consistent with journal entry totals"""
    # Manually calculate account balance and compare with report
```

### Multi-Currency Tests (Required)

```python
def test_multi_currency_conversion():
    """Multi-currency accounts converted correctly"""
    # SGD account 1000 + USD account 500 (rate 1.35) = 1675 SGD

def test_fx_rate_update():
    """Reports recalculated after exchange rate update"""
```

### Performance Tests (Required)

```python
def test_report_generation_performance():
    """1 year data report generation < 2s"""
    # Insert 1000 journal entries, test report generation time
```

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - Account and journal entry tables
- [reporting.md](../ssot/reporting.md) - Report calculation rules
- [market_data.md](../ssot/market_data.md) - Exchange rate data source

---

## 🔗 Deliverables

- [ ] `apps/backend/src/services/reporting.py`
- [ ] `apps/backend/src/services/fx.py`
- [ ] `apps/backend/src/routers/reports.py`
- [ ] `apps/frontend/app/dashboard/page.tsx`
- [ ] `apps/frontend/app/reports/balance-sheet/page.tsx`
- [ ] `apps/frontend/app/reports/income-statement/page.tsx`
- [ ] `apps/frontend/components/charts/`
- [ ] Update `docs/ssot/reporting.md`

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| Cash flow statement | P2 | v1.5 |
| Report materialized views | P2 | Performance optimization phase |
| Budget management | P3 | v2.0 |
| Custom reports | P3 | v2.0 |

---

## ❓ Q&A (Clarification Required)

### Q1: Report Period Definition
> **Question**: How to define "monthly" for income statement?

**✅ Your Answer**: A - Calendar month (1-31), most intuitive

**Decision**: Use calendar month
- All reports default to calendar month grouping (January 1 to January 31)
- API parameter: `period_type` = "natural_month"
- Can be extended to support other periods (week, quarter, year)
- Database query optimization: Group by `DATE_TRUNC('month', entry_date)`

### Q2: Exchange Rate Data Source
> **Question**: What exchange rate data source to use?

**✅ Your Answer**: B - Yahoo Finance API (free)

**Decision**: Use Yahoo Finance as exchange rate source
- Integrate yfinance library or call Yahoo Finance API directly
- Supported currency pairs: SGD/USD, SGD/CNY, SGD/HKD, etc. (via Forex data)
- Caching strategy:
  - Update exchange rates once daily (9:00 AM UTC)
  - Redis cache for 24 hours
  - Support manual refresh button
- Exchange rate history:
  - Record daily rates to `ExchangeRate` table
  - Format: `date, from_currency, to_currency, rate`
- Fallback strategy:
  - If Yahoo Finance unavailable, use last cached rate
  - If no cache, prompt user to set manually

### Q3: Historical Exchange Rate Handling
> **Question**: Should historical transactions use transaction date rate or current rate?

**✅ Your Answer**: A - Use transaction date rate (recorded in journal entries, complies with accounting standards)

**Decision**: Historical exchange rates recorded in journal entries
- JournalLine `fx_rate` field records transaction date exchange rate
- When creating journal entry, automatically query and store current day's rate
- When calculating reports, use fx_rate from journal entry, not real-time rate
- Benefits:
  - ✅ Complies with GAAP standards (transaction date principle)
  - ✅ Reports are traceable (changing rates doesn't impact historical reports)
  - ✅ Foreign exchange gains/losses traceable
- Foreign exchange gain/loss calculation:
  - Original currency amount × transaction date rate = base currency balance (at recording time)
  - Original currency amount × report date rate = report date converted value
  - Difference = foreign exchange gain/loss (Forex Gain/Loss)

### Q4: Chart Library Selection
> **Question**: Use Recharts or ECharts?

**✅ Your Answer**: B - ECharts only, because need K-line and other financial charts

**Decision**: Standardize on ECharts
- ECharts provides rich financial charts: K-line, Candlestick, Volume, etc.
- Use cases:
  - Asset trends: K-line chart (show open, close, high, low)
  - Income/expense analysis: Bar chart, line chart
  - Asset distribution: Pie chart, Sunburst chart
  - Cash flow: Sankey chart (income/expense flow)
- Optimization:
  - Load ECharts sub-modules on demand (reduce bundle size)
  - Use Canvas rendering for large data volume charts (performance optimization)
- Dependencies: `echarts`, `echarts-for-react` (React wrapper)

### Q5: Report Export Formats
> **Question**: What export formats should be supported?

**✅ Your Answer**: CSV as intermediate artifact (data export), PDF as final report (for presentation)

**Decision**: Multi-format export strategy
- **CSV** (intermediate artifact - data export):
  - For data analysis and reprocessing
  - Contains complete fields: account, amount, date, memo, tags, etc.
  - Supports export range filtering (date, account, type)
  - Example: `accounts_export_2025_01.csv`, `transactions_export_2025_01.csv`
  
- **PDF** (final report - for presentation):
  - Generate using ReportLab or WeasyPrint library
  - Contains: balance sheet, income statement, summary charts
  - Professional layout: company name, date, signature line, etc.
  - Embed charts (static images)
  - Example: `Financial_Report_2025_01.pdf`
  
- **Excel** (optional, future iteration):
  - Not implemented now (v1.0 not provided)
  - Can be added in v1.5+ if needed

- **Export API**:
  - `GET /api/reports/balance-sheet/export?format=pdf`
  - `GET /api/reports/transactions/export?format=csv`
  - Backend dynamically generates files, returns download link (or streaming download)

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Report calculation logic + API | 16h |
| Week 2 | Dashboard + chart components | 20h |
| Week 3 | Report pages + export + testing | 16h |

**Total Estimate**: 52 hours (3 weeks)

**Note**: This EPIC can start after EPIC-002 completion, and can be developed in parallel with EPIC-003/004.
