# EPIC-005: Financial Reports & Visualization

> **Status**: ✅ Complete (TDD Aligned)
> **Vision Anchor**: `non-goals-not-budgeting-app`
> **Phase**: 4
> **Duration**: 3 weeks
> **Dependencies**: EPIC-002

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

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `monthly-income-spending`
- `investment-performance`
- `annualized-income-long-term`

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

- [x] `services/reporting.py` - Report generation service
  - [x] `generate_balance_sheet()` - Balance sheet
  - [x] `generate_income_statement()` - Income statement
  - [x] `generate_cash_flow()` - Cash flow statement
  - [x] `get_account_trend()` - Account trend data
  - [x] `get_category_breakdown()` - Category breakdown

### Multi-Currency Handling (Backend)

- [x] `services/fx.py` - Exchange rate service
  - [x] `get_exchange_rate()` - Get exchange rate
  - [x] `convert_to_base()` - Convert to base currency
  - [x] Exchange rate caching and report-side lazy FX resolution
  - [ ] Daily incremental FX sync (tracked by Issue #539)
- [x] Report currency configuration
  - [x] Base currency setting (default SGD)
  - [x] Unified report conversion

### API Endpoints (Backend)

- [x] `GET /reports/balance-sheet`
- [x] `GET /reports/income-statement`
- [x] `GET /reports/cash-flow`
- [x] `GET /reports/trend`
- [x] `GET /reports/breakdown`
- [x] `GET /reports/export`

### Dashboard (Frontend)

- [x] `/dashboard` - Home dashboard
  - [x] Asset overview cards
  - [x] Asset trend line chart
  - [x] Income/expense comparison
  - [x] Account distribution pie chart
  - [x] Recent transactions list

### Report Pages (Frontend)

- [x] `/reports/balance-sheet`
- [x] `/reports/income-statement`
- [x] `/reports/cash-flow`
- [x] Filters and interactions (Date range, Account type, Currency, Tags)

### Chart Components (Frontend)

- [x] `components/charts/TrendChart.tsx`
- [x] `components/charts/PieChart.tsx`
- [x] `components/charts/BarChart.tsx`
- [x] `components/charts/SankeyChart.tsx`

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/reporting/`

### AC5.1: Balance Sheet

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.1.1 | Accounting Equation | `test_balance_sheet_equation` | `reporting/test_reporting.py` | P0 |
| AC5.1.2 | FX Unrealized Gain | `test_fx_unrealized_gain_calculation` | `reporting/test_reporting_fx.py` | P0 |
| AC5.1.3 | Multi-Currency Aggregation | `test_multi_currency_aggregation` | `reporting/test_reporting_fx.py` | P0 |
| AC5.1.4 | Endpoint Response | `test_balance_sheet_endpoint` | `reporting/test_reports_router.py` | P0 |

### AC5.2: Income Statement

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.2.1 | Net Income Calculation | `test_income_statement_calculation` | `reporting/test_reporting.py` | P0 |
| AC5.2.2 | Comprehensive Income | `test_income_statement_comprehensive_income` | `reporting/test_reporting_fx.py` | P1 |
| AC5.2.3 | Date Range Filtering | `test_income_statement_invalid_range` | `reporting/test_reporting.py` | P1 |

### AC5.3: Cash Flow Statement

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.3.1 | Statement Generation | `test_cash_flow_statement` | `reporting/test_reporting.py` | P0 |
| AC5.3.2 | Empty Period Handling | `test_cash_flow_empty_period` | `reporting/test_reporting.py` | P1 |

### AC5.4: FX & Multi-Currency

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.4.1 | FX Fallbacks | `test_reporting_fx_fallbacks` | `reporting/test_reporting_fx.py` | P1 |
| AC5.4.2 | Balance Sheet Net Income FX Fallback | `test_balance_sheet_net_income_fx_fallback` | `reporting/test_reporting_fx.py` | P1 |
| AC5.4.3 | Report FX Lazy Resolution | `test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates` | `reporting/test_reporting_fx.py` | P0 |
| AC5.4.4 | Missing report FX rates produce explicit partial warnings instead of aborting the whole aggregation | `test_aggregate_balances_missing_fx_skips_unconvertible_currency_with_warning` | `reporting/test_reporting_fx_fallbacks.py` | P0 |

### AC5.5: Error Handling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.5.1 | Report Generation Error | `test_reports_router_errors_extended` | `reporting/test_reports_errors.py` | P1 |
| AC5.5.2 | Router Error Handling | `TestReportsRouterErrors` | `reporting/test_reports_router_errors.py` | P1 |

### AC5.6: Investment & Portfolio KPIs

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.6.1 | XIRR calculation accuracy ≤ 0.01% error vs Excel XIRR | `test_AC5_6_1_xirr_matches_single_year_excel_case` | `portfolio/test_performance_service.py` | P0 |
| AC5.6.2 | Annualized return (TWR) computed correctly | `test_AC5_6_2_time_weighted_return_matches_snapshot_period` | `portfolio/test_performance_service.py` | P0 |
| AC5.6.3 | Dividend yield = annual dividends / current value | `test_AC5_6_3_dividend_yield_uses_trailing_dividends_over_current_value` | `portfolio/test_performance_service.py` | P0 |
| AC5.6.4 | Annualized income KPI is surfaced through the dashboard/reporting path and delegates calculation ownership to AC11.8.1 | `test_annualized_income_endpoint_groups_last_12_month_income`, `AC11.8.2/AC11.8.6 renders Annualized Income card with the four metric labels` | `reporting/test_income_annualized_router.py`, `frontend/src/__tests__/dashboardPage.test.tsx` | P0 |
| AC5.6.5 | Unrealized P&L reflected in balance sheet equity | `test_reporting_dashboard_fixture_exact_totals` | `reporting/test_reporting.py` | P0 |
| AC5.6.6 | MWR (money-weighted return) matches XIRR for single cashflow | `test_AC5_6_6_money_weighted_return_matches_xirr_for_single_cashflow` | `portfolio/test_performance_service.py` | P1 |

### AC5.8: Personal Report Package Investment Performance Consumption

EPIC-005 consumes the EPIC-017 schedule endpoint
`GET /api/portfolio/performance/report-schedule` as the
`investment_performance` report section in the personal financial-report
package. The report section must preserve `source_links` and `notes` from the
schedule payload so the package can explain market-data freshness, cost-basis
method, dividends, realized/unrealized P&L, and return metric limitations.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.8.1 | Personal report package defines the `investment_performance` report section as a consumer of the EPIC-017 schedule API | `AC5.8.1 renders investment performance report schedule from the schedule API`; `test_personal_financial_report_package_post_merge_journey`; `test_AC5_8_1_personal_report_package_consumes_investment_schedule_contract` | `apps/frontend/src/__tests__/portfolioPage.test.tsx`; `tests/e2e/test_personal_financial_report_package.py`; `tests/tooling/test_investment_performance_report_contract.py` | P0 |

### AC5.9: Personal Report Package Contract

Issue [#570](https://github.com/wangzitian0/finance_report/issues/570)
defines the package-level API/export contract before the annualized income,
notes, traceability appendix, and representative fixture follow-up work lands.
The contract owns stable section IDs, labels, period/as-of semantics, and
Decimal-safe total field names. Supporting EPICs keep ownership of their
calculations; this contract only describes how their outputs plug into one
personal financial-report package.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.9.1 | Package contract endpoint defines required section IDs, labels, owners, and source endpoints | `test_AC5_9_1_package_contract_endpoint_defines_required_sections` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.9.2 | Package contract exposes Decimal-safe total fields and explicit period/as-of semantics | `test_AC5_9_2_package_contract_marks_decimal_totals_and_period_semantics` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.9.3 | Frontend personal package page renders the contract section IDs and labels from the API contract | `AC5.9.3 renders personal package contract sections from API` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |
| AC5.9.4 | Frontend/export contract surfaces stable export format and CSV columns for package consumers | `AC5.9.4 renders export contract metadata` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P1 |

### AC5.10: Financial Statement Logic Audit Fixes

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.10.1 | Cash-flow statement beginning cash, ending cash, and net cash flow use cumulative cash balances | `test_AC5_10_1_cash_flow_uses_cumulative_cash_balances()` | `reporting/test_financial_logic_audit.py` | P0 |
| AC5.10.2 | Cash-flow operating, investing, and financing totals preserve inflow/outflow signs | `test_AC5_10_2_cash_flow_activity_totals_preserve_signs()` | `reporting/test_financial_logic_audit.py` | P0 |

### AC5.11: Personal Report Package Annualized Income Schedule Consumption

Issue [#566](https://github.com/wangzitian0/finance_report/issues/566)
supplies the report-ready annualized income and long-term compensation schedule
that plugs into the `annualized_income_long_term` package section defined by
AC5.9. Supporting calculations remain owned by EPIC-011.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.11.1 | Package contract marks `annualized_income_long_term` as ready and points to the schedule endpoint | `test_AC5_11_1_package_contract_marks_annualized_schedule_ready` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.11.2 | Frontend personal package page renders annualized income totals and restricted treatment from the schedule endpoint | `AC5.11.2 renders annualized income schedule values and restricted treatment` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |

### AC5.12: Personal Report Package Notes and Disclosure Basis

Issue [#571](https://github.com/wangzitian0/finance_report/issues/571)
supplies the package notes and disclosures for the personal financial-report
package. Notes identify methods, periods, currencies, source states, valuation
basis, data freshness, restricted-asset treatment, and explicit non-compliance
wording. The notes use standards-inspired disclosure discipline but do not
claim statutory filing compliance.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.12.1 | Package notes endpoint returns required note IDs, owner EPICs, source states, and non-compliance wording | `test_AC5_12_1_package_notes_endpoint_returns_required_note_taxonomy` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.12.2 | Package contract marks `notes` as ready and points to the notes endpoint | `test_AC5_12_2_package_contract_marks_notes_ready` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.12.3 | Frontend personal package page renders notes and disclosure basis from the notes endpoint | `AC5.12.3 renders package notes and disclosure basis` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |
| AC5.12.4 | Post-merge package proof asserts notes endpoint, required note IDs, and non-compliance wording | `test_personal_financial_report_package_post_merge_journey` | `tests/e2e/test_personal_financial_report_package.py` | P0 |

### AC5.13: Personal Report Package Traceability Appendix

Issue [#572](https://github.com/wangzitian0/finance_report/issues/572)
supplies the package-specific source-ledger-report traceability appendix. The
appendix does not replace the existing report calculations; it exposes the
traceability anchors, explicit unavailable/not-applicable states, review state,
confidence tier, and completeness warning taxonomy that package consumers need
to audit each report line.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.13.1 | Package traceability endpoint returns source-to-ledger anchors per report line | `test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.13.2 | Traceability appendix exposes explicit completeness states where anchors are unavailable | `test_AC5_13_2_package_traceability_declares_completeness_warnings` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.13.3 | Frontend personal package page renders source, ledger, review, and confidence metadata from the appendix | `AC5.13.3 renders traceability appendix source, ledger, review, and confidence metadata` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |
| AC5.13.4 | Post-merge package proof fails trusted totals without source/ledger anchors or explicit manual inputs | `test_personal_financial_report_package_post_merge_journey` | `tests/e2e/test_personal_financial_report_package.py` | P0 |

**Traceability Result**:
- Total AC IDs: 33
- Requirements converted to AC IDs: 100% (EPIC-005 checklist + must-have standards)
- Requirements with implemented test references: 100%
- Test files: 8

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Balance sheet balanced** | `test_balance_sheet_equation` | 🔴 Critical |
| **Income statement calculation correct** | `test_income_statement_calculation` | 🔴 Critical |
| **Reports consistent with journal entries** | `test_balance_sheet_equation` (indirect verification) | 🔴 Critical |
| Report generation time < 2s | `test_performance.py` (Planned) | Required |
| Data export functional | `test_export_endpoint` | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Report caching | (Performance tests) | ⏳ |
| Chart interactions | (Frontend tests) | ⏳ |
| Budget comparison | (Future) | ⏳ |

### 🚫 Not Acceptable Signals

- Balance sheet not balanced
- Report amounts inconsistent with journal entry totals
- Performance timeout (> 10s)
- Mobile layout broken

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - Account and journal entry tables
- [reporting.md](../ssot/reporting.md) - Report calculation rules
- [market_data.md](../ssot/market_data.md) - Exchange rate data source

---

## 🔗 Deliverables

- [x] `apps/backend/src/services/reporting.py`
- [x] `apps/backend/src/services/fx.py`
- [x] `apps/backend/src/routers/reports.py`
- [x] `apps/frontend/src/app/dashboard/page.tsx`
- [x] `apps/frontend/src/app/reports/`
- [x] `apps/backend/tests/reporting/` - Test suite

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| **Fiscal Year Support** | P2 | Add fiscal year boundary tests |
| **Large Data Performance** | P2 | Add stress tests for large datasets |
| Report materialized views | P2 | Performance optimization phase |

---

## Issues & Gaps

- [ ] Performance tests with high transaction volumes (stress testing) are missing.
- [ ] Tests for partial date ranges (fiscal year boundaries) are missing.

## Personal Financial Report Package Plan

The north-star package is tracked by
[#563](https://github.com/wangzitian0/finance_report/issues/563). EPIC-005 is
the primary product owner for assembling the generated package tracked by
[#567](https://github.com/wangzitian0/finance_report/issues/567).

Scope owned here:

- Balance sheet, income statement, cash-flow view, and report export assembly.
- Report notes that identify methods, currencies, periods, and data freshness.
- Package-level navigation from dashboard/report pages to source-backed report
  outputs.
- Integration of EPIC-011 annualized income and long-term compensation schedules
  tracked by [#566](https://github.com/wangzitian0/finance_report/issues/566).
- Integration of EPIC-017 investment performance schedules tracked by
  [#564](https://github.com/wangzitian0/finance_report/issues/564).

US GAAP and Hong Kong listed-company reporting are reference structures for
coverage and naming discipline. This EPIC does not claim regulated filing
compliance.

Remaining blocker breakdown after the #565 post-merge proof:

- [#570](https://github.com/wangzitian0/finance_report/issues/570) defined the
  package-level API/export contract and stable section IDs through
  `GET /api/reports/package/contract`.
- [#564](https://github.com/wangzitian0/finance_report/issues/564) supplies the
  investment performance schedule input from EPIC-017.
- [#566](https://github.com/wangzitian0/finance_report/issues/566) supplies the
  annualized income and long-term compensation schedule input from EPIC-011
  through `GET /api/reports/package/annualized-income-schedule`.
- [#571](https://github.com/wangzitian0/finance_report/issues/571) codifies the
  standards-inspired note and disclosure taxonomy through
  `GET /api/reports/package/notes` without claiming regulated filing
  compliance.
- [#572](https://github.com/wangzitian0/finance_report/issues/572) defines the
  source-ledger-report traceability appendix for package output through
  `GET /api/reports/package/traceability`.
- [#573](https://github.com/wangzitian0/finance_report/issues/573) supplies the
  representative fixture contract consumed by the package E2E for exact
  Decimal expected outputs.

Closure status:

1. Done: #565 added the behavioral post-merge package journey and provides the
   current baseline proof anchor for
   `personal-financial-report-package` in
   `docs/ssot/critical-proof-matrix.yaml`.
2. Done: #570 defines `GET /api/reports/package/contract` so backend,
   frontend, export, and E2E assertions share stable package section IDs,
   labels, period semantics, and Decimal-safe export fields.
3. Done: deliver the investment-performance schedule input consumed by this
   package (#564, promoted by #596).
4. Done: deliver the annualized income and long-term compensation schedule
   input consumed by this package (#566).
5. Done: deliver notes/disclosures for the package output shape (#571).
6. Done: deliver the traceability appendix for the package output shape (#572).
7. Done: build deterministic fixture coverage (#573) against the same contract
   and schedules, and extend the #565 guard to consume the representative
   fixture contract.

The macro outcome is `covered` in `docs/ssot/critical-proof-matrix.yaml` once
the representative fixture coverage (#573) is merged.

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../user-guide/reports.md](../user-guide/reports.md) — report and dashboard user guide.

---

## ❓ Q&A (Clarification Required)

### Q1: Report Period Definition
> **Decision**: Use calendar month (default).

### Q2: Exchange Rate Data Source
> **Decision**: Yahoo Finance + Caching.

### Q3: Historical Exchange Rate Handling
> **Decision**: Use transaction date rate for historical accuracy.

### Q4: Chart Library Selection
> **Decision**: ECharts (standardized).

### Q5: Report Export Formats
> **Decision**: CSV (data) + PDF (presentation).

---

## 📅 Timeline

| Phase | Content | Status |
|------|------|----------|
| Week 1 | Report calculation logic + API | ✅ Done |
| Week 2 | Dashboard + chart components | ✅ Done |
| Week 3 | Report pages + export + testing | ✅ Done |

---

## 🆕 UI Gap Audit (April 2026) — Net Worth Time Series

**Origin**: UI gap audit against [vision.md](../../vision.md) North Star ("总资产、月度盈亏、长期趋势"). Current dashboard shows point-in-time balance sheet only; no historical net-worth chart.

### Acceptance Criteria

- [x] **AC5.7.1** Net worth time-series API endpoint `GET /api/reports/net-worth/timeseries?from=YYYY-MM-DD&to=YYYY-MM-DD&granularity=monthly|daily` returns `[{date, total_assets, total_liabilities, net_worth}]`
- [x] **AC5.7.2** Net worth chart component on dashboard renders ECharts line chart with date X-axis and net-worth Y-axis
- [x] **AC5.7.3** Net worth time-series respects multi-currency: each point converted to base currency using historical FX rate per `transaction-date rate` rule
- [x] **AC5.7.4** Time range selector (1M / 3M / 6M / 1Y / All) on dashboard toggles `from` parameter for chart
- [x] **AC5.7.5** Empty-state placeholder rendered when fewer than 2 data points exist (cannot draw line)
- [x] **AC5.7.6** Frontend unit test mounts NetWorthTimeSeries component and asserts chart container exists

**Priority**: P1 (high) — needed for vision parity but not blocking user adoption.
**Estimated effort**: 3-5 days backend + 2-3 days frontend.
