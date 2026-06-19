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
| AC5.3.3 | Test getting account trend with different period. | `test_account_trend_with_period` | `api/test_reports_router.py` | P1 |
| AC5.3.4 | Test getting category breakdown. | `test_category_breakdown_success` | `api/test_reports_router.py` | P1 |
| AC5.3.5 | Test getting category breakdown with different period. | `test_category_breakdown_with_period` | `api/test_reports_router.py` | P1 |

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
| AC5.5.3 | Test that unauthenticated clients cannot access reports endpoints. | `test_unauthenticated_access` | `api/test_reports_router.py` | P1 |
| AC5.5.4 | Reports Router Tests | `test_reports_router` | `reporting/test_reports_router.py` | P1 |
| AC5.5.5 | GET /reports/{type}/snapshots returns persisted snapshots. | `test_list_report_snapshots_returns_created_snapshots` | `api/test_reports_router.py` | P1 |

### AC5.6: Investment & Portfolio KPIs

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.6.1 | XIRR calculation accuracy ≤ 0.01% error vs Excel XIRR | `test_AC5_6_1_xirr_matches_single_year_excel_case` | `portfolio/test_performance_service.py` | P0 |
| AC5.6.2 | Annualized return (TWR) computed correctly | `test_AC5_6_2_time_weighted_return_matches_snapshot_period` | `portfolio/test_performance_service.py` | P0 |
| AC5.6.3 | Dividend yield = annual dividends / current value | `test_AC5_6_3_dividend_yield_uses_trailing_dividends_over_current_value` | `portfolio/test_performance_service.py` | P0 |
| AC5.6.4 | Annualized income KPI is surfaced through the dashboard/reporting path and delegates calculation ownership to AC11.8.1 | `test_annualized_income_endpoint_groups_last_12_month_income`, `AC11.8.2/AC11.8.6 renders Annualized Income card with the four metric labels` | `reporting/test_income_annualized_router.py`, `frontend/src/__tests__/dashboardPage.test.tsx` | P0 |
| AC5.6.5 | Unrealized P&L reflected in balance sheet equity | `test_reporting_dashboard_fixture_exact_totals` | `reporting/test_reporting.py` | P0 |
| AC5.6.6 | MWR (money-weighted return) matches XIRR for single cashflow | `test_AC5_6_6_money_weighted_return_matches_xirr_for_single_cashflow` | `portfolio/test_performance_service.py` | P1 |
| AC5.6.7 | Report output lists currencies that used average-rate spot fallback. | `test_income_statement_includes_average_rate_fallback_warning` | `reporting/test_reporting_fx_revaluation_integration.py` | P1 |
| AC5.6.8 | Account trend raises when prefetched non-base FX rate is missing. | `test_account_trend_raises_when_prefetched_rate_missing` | `reporting/test_reporting_extreme_fallbacks.py` | P1 |
| AC5.6.9 | Category breakdown raises when prefetched non-base FX rate is missing. | `test_category_breakdown_raises_when_prefetched_rate_missing` | `reporting/test_reporting_extreme_fallbacks.py` | P1 |
| AC5.6.10 | Cash flow raises when start-date non-base FX rate is missing. | `test_cash_flow_raises_when_start_date_rate_missing` | `reporting/test_reporting_extreme_fallbacks.py` | P1 |
| AC5.6.11 | Cash flow raises when end-date rate missing; FxRateError propagated. | `test_cash_flow_raises_when_end_date_rate_missing` | `reporting/test_reporting_extreme_fallbacks.py` | P1 |

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
| AC5.11.3 | Annualized income package schedule converts mixed-currency income and restricted totals into one reporting currency | `test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals` | `reporting/test_annualized_income_schedule.py` | P0 |

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
| AC5.13.5 | Package traceability endpoint returns current-user dynamic source identifiers and excludes unrelated-user anchors | `test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers` | `api/test_personal_report_package_contract.py` | P0 |

### AC5.14: Framework Policy Result Consumption

EPIC-005 assembles report packages from framework policy results owned by
[EPIC-020](EPIC-020.framework-aware-personal-reporting.md). It renders
statements, notes, exports, and traceability; it must not own US/HK
recognition, measurement, or classification rules.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.14.1 | Reporting docs declare that EPIC-005 consumes framework policy results for US/HK package output and does not own framework-specific accounting decisions | `test_AC5_14_1_reporting_assembles_framework_policy_results_only` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC5.15: Backend Reporting Integration Journey

Issue [#341](https://github.com/wangzitian0/finance_report/issues/341)
requested a T6 reporting proof. Reporting ownership is EPIC-005 in this
repository; EPIC-006 remains the AI advisor surface. This AC provides the
backend Tier-1 integration proof for the multi-currency reporting cycle without
changing the later PDF export scope tracked by
[#205](https://github.com/wangzitian0/finance_report/issues/205).

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.15.1 | Multi-currency posted entries generate balanced balance sheet, income statement, and cash-flow reports in base currency | `test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf` | `integration/test_reporting_e2e.py` | P0 |

### AC5.16: Report Trust Signals and Restricted-Asset Defaults

The June 2026 UI/report audit found that core report pages were technically
covered but did not render important trust signals already present in backend
payloads. This group makes report default semantics and partial-data warnings
visible to users.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.16.1 | Balance sheet defaults restricted holdings to excluded, exposes an include toggle, and renders equation component detail | `test_AC5_16_1_balance_sheet_defaults_to_excluding_restricted_holdings` / `AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date` | `reporting/test_reports_router.py`, `frontend/src/__tests__/balanceSheetPage.test.tsx` | P0 |
| AC5.16.2 | Balance sheet, income statement, and cash-flow report pages surface backend `fx_warnings` instead of silently rendering partial totals | `test_AC5_16_2_cash_flow_response_preserves_fx_warnings` / page warning assertions | `reporting/test_reports_router.py`, `frontend/src/__tests__/balanceSheetPage.test.tsx`, `frontend/src/__tests__/incomeStatementPage.test.tsx`, `frontend/src/__tests__/cashFlowPage.test.tsx` | P0 |
| AC5.16.3 | Personal report package traceability renders concrete source and ledger identifiers when the appendix provides them | `AC5.13.3 renders traceability appendix source, ledger, review, and confidence metadata` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |
| AC5.16.4 | Personal report package traceability lines expose source classes, proof level, anchor count, and blocker codes for report-line confidence review | `test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors`, `test_AC5_13_2_package_traceability_declares_completeness_warnings` | `api/test_personal_report_package_contract.py` | P0 |

### AC5.17: Authenticated Report CSV Exports

The report export workflow must preserve the authenticated API boundary and
support every first-class financial statement page that exposes an export
action.

| AC | Acceptance Criteria | Test(s) | File(s) | Priority |
|----|--------------------|---------|---------|----------|
| AC5.17.1 | Balance sheet, income statement, and cash-flow pages download CSV through the authenticated API wrapper, and the backend CSV export supports cash-flow reports with date range and currency filters | `AC5.17.1 downloads cash-flow CSV through authenticated apiDownload`, `test_AC5_17_1_cash_flow_export_returns_csv` | `frontend/src/__tests__/cashFlowPage.test.tsx`, `reporting/test_reports_router.py` | P0 |
| AC5.17.2 | Personal report package page exposes an authenticated CSV export action after framework selection, using the package export contract and selected framework ID | `AC5.17.2 downloads package CSV through authenticated apiDownload` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |

### AC5.18: Per-Node Confidence Tier on Balance-Sheet Payloads

Axiom B makes confidence a first-class, measured property. Each balance-sheet
line carries the confidence tier of its contributing ledger facts, and the Net
Worth aggregate rolls up to the worst-input tier (see
[confirmation-workflow.md](../ssot/confirmation-workflow.md) → Confidence Tier
Rollup) — a defined rollup, not an invented number. Income statement, cash flow,
and the monthly cards are a follow-up; provenance (#888) is the co-equal sibling axis.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.18.1 | Each balance-sheet line carries the worst-input confidence tier of its contributing journal entries | `test_AC5_18_1_lines_carry_worst_input_confidence_tier()` | `reporting/test_balance_sheet_confidence.py` | P1 |
| AC5.18.2 | The Net Worth aggregate rolls up to the worst-input tier across rated lines, and is null when nothing is rated | `test_AC5_18_2_net_worth_rolls_up_to_worst_input_tier()` | `reporting/test_balance_sheet_confidence.py` | P1 |

### AC5.19: Report Package Snapshot Artifact

The personal financial-report package must be a durable artifact, not only a
live page assembled from current endpoints. Snapshot generation freezes the
period, currency, selected framework, readiness state, source anchors,
traceability lines, and section payloads so the user can reopen and export the
same package after later ledger or market-data changes.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.19.1 | `POST /api/reports/package/generate` creates an immutable package snapshot that records period, currency, framework, readiness, source trust, traceability, and section payloads; blocked readiness may generate only a draft, while ready readiness generates trusted output | `test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.19.2 | `GET /api/reports/package/snapshots` and `GET /api/reports/package/snapshots/{snapshot_id}` list and reopen only the current user's saved package snapshots, and reopening returns the original payload after live report inputs change | `test_AC5_19_2_package_snapshot_get_is_user_scoped_and_immutable` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.19.3 | Package JSON and CSV downloads are derived from a saved snapshot rather than recalculating live data | `test_AC5_19_3_package_snapshot_exports_are_snapshot_derived` | `api/test_personal_report_package_contract.py` | P0 |
| AC5.19.4 | The package page shows recent snapshots, can generate a new snapshot, and downloads JSON/CSV from the saved snapshot artifact | `AC5.19.4 generates and downloads package snapshots` | `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |

### AC5.20: Year-Scale Reporting Validation ([#951](https://github.com/wangzitian0/finance_report/issues/951))

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.20.1 | At a full year's transaction volume (~1000 entries) the balance sheet, income statement, and cash flow tie out and generate within a generous wall-clock backstop — guarding the income-statement aggregation against a silent O(n^2) regression | `test_AC5_20_year_scale_reporting_ties_out_within_budget` | `reporting/test_year_scale_reporting.py` | P1 |

### AC5.32: Income Module Typed Currency + Typed-Intermediate Response ([#1009](https://github.com/wangzitian0/finance_report/issues/1009))

Tech-debt hardening of `apps/backend/src/routers/income.py` (Tier 3 of #1000):
replace soft `str` currency handling with a shared validated/normalized
`CurrencyCode` type, build the response from a typed intermediate
(`AnnualizedIncomeTotals`) instead of a string-keyed dict, and declare an
explicit FX-failure response model. Monetary values stay `Decimal`.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.32.1 | `AnnualizedIncomeResponse.currency` is the shared typed `CurrencyCode` (validated length + normalized), not a soft `str` | `test_AC5_32_1_currency_code_type_validates_and_normalizes` | `reporting/test_income_typed_currency.py` | P2 |
| AC5.32.2 | Income totals accumulate in a typed `AnnualizedIncomeTotals` Decimal intermediate, not a string-keyed dict | `test_AC5_32_2_annualized_income_totals_is_typed_intermediate` | `reporting/test_income_typed_currency.py` | P2 |
| AC5.32.3 | `resolve_line_currency` centralizes the `line\|\|account\|\|base` currency fallback + normalization | `test_AC5_32_3_resolve_line_currency_uses_canonical_fallback_chain` | `reporting/test_income_typed_currency.py` | P2 |
| AC5.32.4 | An explicit FX-failure response model (`FxConversionErrorResponse`) is declared for the income endpoint | `test_AC5_32_4_fx_conversion_error_response_model_declared` | `reporting/test_income_typed_currency.py` | P2 |
| AC5.32.5 | Currency normalization is a single shared helper (`normalize_currency_code`), not duplicated `.strip().upper()` | `test_AC5_32_5_normalize_currency_code_is_shared_helper` | `reporting/test_income_typed_currency.py` | P2 |
| AC5.32.6 | The endpoint normalizes a soft (lower-case) base-currency setting in its response | `test_AC5_32_6_endpoint_returns_normalized_currency_for_soft_base_config` | `reporting/test_income_typed_currency.py` | P2 |

### AC5.33: Report Page Shell + Toolbar Primitives ([#751](https://github.com/wangzitian0/finance_report/issues/751))

Slice 3 of the frontend reuse architecture (#751). Extract the repeated
report-route boilerplate (header, AI-interpretation / home / CSV-export toolbar,
loading skeleton, error+retry state) into shared composition primitives
(`ReportPageShell`, `ReportToolbar`, `AiPromptAction`) so report routes stay thin
and behavior is identical across balance-sheet, income-statement, and cash-flow.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.33.1 | `ReportPageShell` renders title, description, and toolbar slot, and shows the report body when not loading or errored | `AC5.33.1 renders title, description, toolbar, and body content` | `apps/frontend/src/__tests__/reportPageShell.test.tsx` | P1 |
| AC5.33.2 | `ReportPageShell` renders the loading skeleton (and not the body) while `isLoading` | `AC5.33.2 shows loading skeleton while loading` | `apps/frontend/src/__tests__/reportPageShell.test.tsx` | P1 |
| AC5.33.3 | `ReportPageShell` renders the error message with a working Retry action on `isError` | `AC5.33.3 shows error message and retries on click` | `apps/frontend/src/__tests__/reportPageShell.test.tsx` | P1 |
| AC5.33.4 | `ReportToolbar` composes the AI-prompt action, Home link, and CSV export action from its props | `AC5.33.4 renders AI prompt, home link, and CSV export` | `apps/frontend/src/__tests__/reportToolbar.test.tsx` | P1 |
| AC5.33.5 | `AiPromptAction` links to the chat route with a URL-encoded prompt | `AC5.33.5 links to chat with url-encoded prompt` | `apps/frontend/src/__tests__/reportToolbar.test.tsx` | P1 |

### AC5.34: Report Filter Controls + Filter Hook ([#751](https://github.com/wangzitian0/finance_report/issues/751))

Slice 3 of #751. Provide reusable date and currency filter controls plus a
`useReportFilters` query-layer hook that owns the filter state and derives the
query string, CSV export path, and AI-prompt text so route pages only express
page-level intent.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.34.1 | `DateFilterControl` renders a labelled date input and emits changes | `AC5.34.1 renders labelled date input and emits change` | `apps/frontend/src/__tests__/reportFilters.test.tsx` | P1 |
| AC5.34.2 | `CurrencyFilterControl` renders a labelled currency select with the provided options and emits changes | `AC5.34.2 renders currency options and emits change` | `apps/frontend/src/__tests__/reportFilters.test.tsx` | P1 |
| AC5.34.3 | `useReportFilters` builds a query string from its date and currency state | `AC5.34.3 builds query string from filter state` | `apps/frontend/src/__tests__/useReportFilters.test.ts` | P1 |
| AC5.34.4 | `useReportFilters` derives the CSV export path for the given report type | `AC5.34.4 derives csv export path for report type` | `apps/frontend/src/__tests__/useReportFilters.test.ts` | P1 |
| AC5.34.5 | `useReportFilters` updates the query string when the currency changes | `AC5.34.5 updates query string when currency changes` | `apps/frontend/src/__tests__/useReportFilters.test.ts` | P1 |

### AC5.35: Dashboard Aggregation Moved Into Hook Layer ([#751](https://github.com/wangzitian0/finance_report/issues/751))

Slice 3 of #751. Move the dashboard's parallel API aggregation and report
normalization out of the route page and into a `useDashboardData` hook (over the
shared `apiFetch` transport), so the home route composes data instead of
fetching and normalizing it inline. Monetary values stay decimal strings.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.35.1 | `useDashboardData` aggregates the dashboard endpoints over `apiFetch` and exposes a single loading flag | `AC5.35.1 aggregates dashboard endpoints over apiFetch` | `apps/frontend/src/__tests__/useDashboardData.test.ts` | P1 |
| AC5.35.2 | `useDashboardData` normalizes missing balance-sheet / income / annualized fields to safe decimal-string defaults | `AC5.35.2 normalizes missing report fields to defaults` | `apps/frontend/src/__tests__/useDashboardData.test.ts` | P1 |
| AC5.35.3 | `useDashboardData` surfaces an error message and a retry that refetches when aggregation fails | `AC5.35.3 surfaces error and retries on failure` | `apps/frontend/src/__tests__/useDashboardData.test.ts` | P1 |
| AC5.35.4 | `useDashboardData` tolerates a failing chat-suggestions endpoint without failing the whole dashboard | `AC5.35.4 tolerates failing chat suggestions endpoint` | `apps/frontend/src/__tests__/useDashboardData.test.ts` | P1 |

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
- Integration of EPIC-020 framework policy results for US-like and HK-like
  personal report package variants.

US GAAP and Hong Kong listed-company reporting are target reference structures
for coverage and naming discipline through EPIC-020. This EPIC renders personal
management reports and does not claim regulated filing compliance.

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
   the derived critical-proof matrix (source `docs/ssot/critical-proof-outcomes.yaml`).
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
8. Done: [#649](https://github.com/wangzitian0/finance_report/issues/649)
   hardened the covered package proof with dynamic traceability identifiers and
   pinned brokerage/dividend/market-price fixture expected outputs.

The macro outcome is `covered` in the derived critical-proof matrix (source `docs/ssot/critical-proof-outcomes.yaml`) once
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

**Origin**: UI gap audit against [Project Vision](../target.md) North Star ("总资产、月度盈亏、长期趋势"). Current dashboard shows point-in-time balance sheet only; no historical net-worth chart.

### Acceptance Criteria

- [x] **AC5.7.1** Net worth time-series API endpoint `GET /api/reports/net-worth/timeseries?from=YYYY-MM-DD&to=YYYY-MM-DD&granularity=monthly|daily` returns `[{date, total_assets, total_liabilities, net_worth}]`
- [x] **AC5.7.2** Net worth chart component on dashboard renders ECharts line chart with date X-axis and net-worth Y-axis
- [x] **AC5.7.3** Net worth time-series respects multi-currency: each point converted to base currency using historical FX rate per `transaction-date rate` rule
- [x] **AC5.7.4** Time range selector (1M / 3M / 6M / 1Y / All) on dashboard toggles `from` parameter for chart
- [x] **AC5.7.5** Empty-state placeholder rendered when fewer than 2 data points exist (cannot draw line)
- [x] **AC5.7.6** Frontend unit test mounts NetWorthTimeSeries component and asserts chart container exists

**Priority**: P1 (high) — needed for vision parity but not blocking user adoption.
**Estimated effort**: 3-5 days backend + 2-3 days frontend.

### AC5.36: Report Snapshots Typed Contract ([#1008](https://github.com/wangzitian0/finance_report/issues/1008))

Tier 2 of #1000. `GET /reports/{report_type}/snapshots` declares a typed
`list[ReportSnapshotSummary]` response (built from the ORM via `from_attributes`
instead of a hand-rolled dict), and `report_type` is typed as the snapshot enum so
an unknown value is rejected with 422 instead of silently returning an empty list.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.36.1 | An unknown `report_type` returns 422 | `test_AC5_36_1_report_snapshots_unknown_type_returns_422` | `api/test_typed_contract_sweep.py` | P2 |
| AC5.36.2 | A valid `report_type` returns a typed list | `test_AC5_36_2_report_snapshots_valid_type_returns_typed_list` | `api/test_typed_contract_sweep.py` | P2 |

### AC5.37: Trust-First Reports Cockpit ([#1209](https://github.com/wangzitian0/finance_report/issues/1209))

The Reports landing page must answer whether report output is currently
trustworthy before it presents the report navigation cards. It consumes the
existing package readiness/source-trust contract and does not duplicate
readiness derivation or source-trust rules in the frontend.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC5.37.1 | The Reports cockpit renders package readiness state, blocker count, next action, and source-gap summary before report cards | `AC5.37.1 renders trust-first readiness before report cards` | `frontend/src/__tests__/reportsCockpit.test.tsx` | P1 |
| AC5.37.2 | If readiness loading fails, the Reports cockpit shows a contained unavailable state while preserving report navigation | `AC5.37.2 preserves report navigation when readiness is unavailable` | `frontend/src/__tests__/reportsCockpit.test.tsx` | P1 |
