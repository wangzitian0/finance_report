# EPIC-005: Financial Reports & Visualization

> **Status**: ⏳ Pending 
> **Phase**: 4 
> **Duration**: 3 weeks 
> **Dependencies**: EPIC-002 (can and EPIC-003/004 ) 

---

## 🎯 Objective

generatestandardfinancetable (assetliabilitytable, table, cashtable), can assetandtrend, use finance. 

**Core Constraints**:
```
assetliabilitytable: Assets = Liabilities + Equity
table: Net Income = Income - Expenses
Accounting equationverification: reportRequiredcomplyAccounting equation
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 📊 **Accountant** | reportaccurate | tableRequiredcomply will then, can |
| 🏗️ **Architect** | calculate can | report need cacheorview |
| 💻 **Developer** | chartimplementation | Recharts lightweight, ECharts complexchart |
| 📋 **PM** | use | report need andsample, non- will use also can |
| 🧪 **Tester** | calculatevalidate | andcalculate for compare, < 1% |

---

## ✅ Task Checklist

### reportcalculate (Backend)

- [ ] `services/reporting.py` - reportgenerateservice
 - [ ] `generate_balance_sheet()` - assetliabilitytable
 - accountclassbalance
 - asset = liability + equity validate
 - [ ] `generate_income_statement()` - table
 - income/
 - month/quarter/year for compare 
 - [ ] `generate_cash_flow()` - cashtable (P2)
 - //minutesclass
 - [ ] `get_account_trend()` - accounttrend
 - [ ] `get_category_breakdown()` - minutesclass compare 

### process (Backend)

- [ ] `services/fx.py` - exchange rateservice
 - [ ] `get_exchange_rate()` - getexchange rate
 - [ ] `convert_to_base()` - to 
 - [ ] exchange ratecache (eachupdate)
- [ ] reportconfiguration
 - [ ] (default SGD)
 - [ ] report

### API endpoint (Backend)

- [ ] `GET /api/reports/balance-sheet` - assetliabilitytable
 - parameter: `as_of_date`, `currency`
- [ ] `GET /api/reports/income-statement` - table
 - parameter: `start_date`, `end_date`, `currency`
- [ ] `GET /api/reports/cash-flow` - cashtable (P2)
- [ ] `GET /api/reports/trend` - trend
 - parameter: `account_id`, `period` (daily/weekly/monthly)
- [ ] `GET /api/reports/breakdown` - minutesclass compare 
 - parameter: `type` (income/expense), `period`
- [ ] `GET /api/reports/export` - export Excel/CSV

### dashboard (Frontend)

- [ ] `/dashboard` - dashboard
 - [ ] asset (asset, liability, asset)
 - [ ] assettrend ( 12 month)
 - [ ] for compare (month)
 - [ ] accountminutes (class)
 - [ ] most table
 - [ ] not yet match

### reportpage (Frontend)

- [ ] `/reports/balance-sheet` - assetliabilitytable
 - [ ] layout (asset | liability | equity)
 - [ ] accounthierarchy/
 - [ ] date
 - [ ] export
- [ ] `/reports/income-statement` - table
 - [ ] income/minutesclass
 - [ ] compare / compare for compare 
 - [ ] timerange
- [ ] `/reports/cash-flow` - cashtable (P2)
- [ ] and
 - [ ] daterange
 - [ ] accountclass
 - [ ] 
 - [ ] tag

### chartcomponent (Frontend)

- [ ] `components/charts/TrendChart.tsx` - trend
- [ ] `components/charts/PieChart.tsx` - 
- [ ] `components/charts/BarChart.tsx` - 
- [ ] `components/charts/SankeyChart.tsx` - (P2)

---

## 📏 good not good standard

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **assetliabilitytable** | Assets = Liabilities + Equity | 🔴 critical |
| **tablecalculatecorrect** | validate 5 month | 🔴 critical |
| **reportandjournal entry** | reportamount can to journal entry | 🔴 critical |
| reportgeneratetime < 2s | can test (1 year) | Required |
| | should layout | Required |
| export can use | Excel/CSV download | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| reportcache (decreasecalculate) | Redis cache in | ⏳ |
| chart (drill-down) | | ⏳ |
| for compare | vs | ⏳ |
| customreport | use dimension | ⏳ |
| report | month | ⏳ |

### 🚫 Not Acceptable Signals

- assetliabilitytable not 
- reportamountandjournal entrytotal not 
- chartandreport not 
- can timeout (> 10s)
- layoutwrong

---

## 🧪 Test Scenarios

### reportcalculatetest (Required)

```python
def test_balance_sheet_equation():
 """assetliabilitytable: Assets = Liabilities + Equity"""
 report = generate_balance_sheet(as_of_date=date(2025, 12, 31))
 assert abs(report.total_assets - (report.total_liabilities + report.total_equity)) < 0.01

def test_income_statement_calculation():
 """table: Net Income = Income - Expenses"""
 report = generate_income_statement(start=date(2025, 1, 1), end=date(2025, 12, 31))
 assert report.net_income == report.total_income - report.total_expenses

def test_report_matches_journal():
 """reportamountandjournal entrytotal"""
 # calculateaccountbalance, andreport for compare 
```

### test (Required)

```python
def test_multi_currency_conversion():
 """accountcorrect"""
 # SGD account 1000 + USD account 500 (exchange rate 1.35) = 1675 SGD

def test_fx_rate_update():
 """exchange rateupdatereport"""
```

### can test (Required)

```python
def test_report_generation_performance():
 """1 yearreportgenerate < 2s"""
 # 1000 journal entry, testreportgeneratetime
```

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - accountandjournal entrytable
- [reporting.md](../ssot/reporting.md) - reportcalculate then 
- [market_data.md](../ssot/market_data.md) - exchange rate

---

## 🔗 Deliverables

- [ ] `apps/backend/src/services/reporting.py`
- [ ] `apps/backend/src/services/fx.py`
- [ ] `apps/backend/src/routers/reports.py`
- [ ] `apps/frontend/app/dashboard/page.tsx`
- [ ] `apps/frontend/app/reports/balance-sheet/page.tsx`
- [ ] `apps/frontend/app/reports/income-statement/page.tsx`
- [ ] `apps/frontend/components/charts/`
- [ ] update `docs/ssot/reporting.md`

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| cashtable | P2 | v1.5 |
| reportview | P2 | can optimizationphase |
| | P3 | v2.0 |
| customreport | P3 | v2.0 |

---

## ❓ Q&A (Clarification Required)

### Q1: report
> **Question**: table "month" such as ? 

**✅ Your Answer**: A - month (1-31), most intuitive

**Decision**: usemonth
- have/has reportdefaultmonthminutes (1 month 1 1 month 31 )
- API parameter: `period_type` = "natural_month"
- can extensionsupportDuration (week, quarter, year)
- databasequeryoptimization: `DATE_TRUNC('month', entry_date)` minutes

### Q2: exchange rate
> **Question**: use what exchange rate? 

**✅ Your Answer**: B - Yahoo Finance API ()

**Decision**: use Yahoo Finance as/for exchange rate
- yfinance orCall Yahoo Finance API
- support currency for:SGD/USD, SGD/CNY, SGD/HKD etc. ( excessively Forex )
- cachestrategy:
 - eachupdateexchange rate ( UTC 9:00)
 - Redis cache 24 hours
 - support
- exchange rate:
 - eachexchange rate to `ExchangeRate` table
 - : `date, from_currency, to_currency, rate`
- downgradesolution:
 - such as Yahoo Finance not can use, usecacheexchange rate
 - such as no/none cache, notice use 

### Q3: exchange rateprocess
> **Question**: useexchange rate still/also is exchange rate? 

**✅ Your Answer**: A - useexchange rate ( in/at journal entry in, comply will then)

**Decision**: exchange rate in/at journal entry
- JournalLine `fx_rate` field exchange rate
- journal entrycreate, queryexchange rate
- reportcalculateusejournal entry in fx_rate, not exchange rate
- good:
 - ✅ comply GAAP then ( then)
 - ✅ report can (modifyexchange rate not Impactreport)
 - ✅ can 
- calculate:
 - amount × exchange rate = balance (bookkeeping)
 - amount × reportexchange rate = report
 - = (Forex Gain/Loss)

### Q4: chart
> **Question**: use Recharts still/also is ECharts? 

**✅ Your Answer**: B - ECharts, as/for need need to K etc. chart

**Decision**: use ECharts
- ECharts chart:K , Candlestick, Volume etc. 
- should use :
 - assettrend:K (, , highest, most low)
 - analysis:, 
 - assetminutes:, Sunburst 
 - cash:Sankey ()
- optimization:
 - need ECharts module (decrease bundle )
 - use Canvas chart ( can optimization)
- Dependencies:`echarts`, `echarts-for-react` (React wrapper)

### Q5: reportexport
> **Question**: need need to support which export? 

**✅ Your Answer**: CSV as/for in (export), PDF as/for most report (demo use)

**Decision**: exportstrategy
- **CSV** (in - export):
 - use in/at analysis, 
 - containcompletefield:account, amount, date, , tag etc. 
 - supportexportrange (date, account, class)
 - sample:`accounts_export_2025_01.csv`, `transactions_export_2025_01.csv`
 
- **PDF** (most report - demo use):
 - use ReportLab or WeasyPrint generate
 - contain:assetliabilitytable, table, aggregatechart
 - :, date, etc. 
 - chart (static)
 - sample:`Financial_Report_2025_01.pdf`
 
- **Excel** (optional, ):
 - not implementation (v1.0 not )
 - such as need need to can in/at v1.5+ 

- **export API**:
 - `GET /api/reports/balance-sheet/export?format=pdf`
 - `GET /api/reports/transactions/export?format=csv`
 - Backenddynamicgenerate, download (ordownload)

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | reportcalculatelogic + API | 16h |
| Week 2 | dashboard + chartcomponent | 20h |
| Week 3 | reportpage + export + test | 16h |

****: 52 hours (3 weeks)

****: EPIC can in/at EPIC-002 complete, and EPIC-003/004 developer. 
