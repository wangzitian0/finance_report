# EPIC-005: Financial Reports & Visualization
<!-- epic-file: design-doc -->

<!-- Zero AC rows by design (#1821 Wave B / #1858): the delivered financial-reports
     and visualization design record; all ACs migrated to the `reporting`
     package roadmap (fe-viz-reports group; one row -- the CSV-download-
     wrapper AC -- to meta/fe-http-client as a generic HTTP-client capability). -->

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

> **Migration note**: `services/fx.py` splits under the package migration —
> conversion *math* stays in `audit`; rate *lookup* moves to the `pricing`
> package (#1610). The checklist below records the shipped pre-migration state.

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

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.balance-sheet.1-4` (migration closeout continuation, #1663 /
> #1716).

### AC5.2: Income Statement

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.income-statement.1-3` (migration closeout continuation,
> #1663 / #1716).

### AC5.3: Cash Flow Statement

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.cash-flow.1-5` (migration closeout continuation, #1663 /
> #1716).

### AC5.4: FX & Multi-Currency

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.fx.1-4` (migration closeout continuation, #1663 / #1716).

### AC5.5: Error Handling

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.errors.1-5` (migration closeout continuation, #1663 / #1716).
>
> *(AC5.5.2 removed and AC5.5.4 removed with the group — their class/file-level citations are now representative function-level citations in the package roadmap)*

### AC5.6: Investment & Portfolio KPIs

> *(AC5.6.5 removed and AC5.6.7 removed and AC5.6.8 removed and AC5.6.9 removed and AC5.6.10 removed and AC5.6.11 removed — migrated to the `reporting` package roadmap as `AC-reporting.kpis.2-7`; AC5.6.4's backend endpoint half migrated as `AC-reporting.kpis.1` while its frontend dashboard-card proof stays in the row below. Migration closeout continuation, #1663 / #1716)*
>
> *(AC5.6.1 removed and AC5.6.2 removed and AC5.6.3 removed and AC5.6.6 removed — portfolio-owned performance math that lived in this reporting EPIC; migrated to the `portfolio` package roadmap as `AC-portfolio.metrics.1-4`, migration closeout continuation, #1663 / #1717.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.6.4 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.1`, #1821 Wave B)

### AC5.8: Personal Report Package Investment Performance Consumption

EPIC-005 consumes the EPIC-017 schedule endpoint
`GET /api/portfolio/performance/report-schedule` as the
`investment_performance` report section in the personal financial-report
package. The report section must preserve `source_links` and `notes` from the
schedule payload so the package can explain market-data freshness, cost-basis
method, dividends, realized/unrealized P&L, and return metric limitations.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.8.1 removed, canonical: its backend contract half migrated to the `reporting` package roadmap as `AC-reporting.package-investment.1` (migration closeout continuation, #1663 / #1716) and its frontend render proof migrated to `AC-reporting.fe-viz-reports.2`, #1821 Wave B)

### AC5.9: Personal Report Package Contract

Issue [#570](https://github.com/wangzitian0/finance_report/issues/570)
defines the package-level API/export contract before the annualized income,
notes, traceability appendix, and representative fixture follow-up work lands.
The contract owns stable section IDs, labels, period/as-of semantics, and
Decimal-safe total field names. Supporting EPICs keep ownership of their
calculations; this contract only describes how their outputs plug into one
personal financial-report package.

> *(AC5.9.1 removed and AC5.9.2 removed — migrated to the `reporting` package roadmap as `AC-reporting.package-contract.1-2`; the frontend rows below stay here. Migration closeout continuation, #1663 / #1716.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.9.3 removed and AC5.9.4 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.3` through `.4`, #1821 Wave B)

### AC5.10: Financial Statement Logic Audit Fixes

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.logic-audit.1-2` (migration closeout continuation, #1663 /
> #1716).

### AC5.11: Personal Report Package Annualized Income Schedule Consumption

Issue [#566](https://github.com/wangzitian0/finance_report/issues/566)
supplies the report-ready annualized income and long-term compensation schedule
that plugs into the `annualized_income_long_term` package section defined by
AC5.9. Supporting calculations remain owned by EPIC-011.

> *(AC5.11.1 removed and AC5.11.3 removed — migrated to the `reporting` package roadmap as `AC-reporting.package-annualized.1-2`; the frontend row below stays here. Migration closeout continuation, #1663 / #1716.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.11.2 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.5`, #1821 Wave B)

### AC5.12: Personal Report Package Notes and Disclosure Basis

Issue [#571](https://github.com/wangzitian0/finance_report/issues/571)
supplies the package notes and disclosures for the personal financial-report
package. Notes identify methods, periods, currencies, source states, valuation
basis, data freshness, restricted-asset treatment, and explicit non-compliance
wording. The notes use standards-inspired disclosure discipline but do not
claim statutory filing compliance.

> *(AC5.12.1 removed and AC5.12.2 removed and AC5.12.4 removed — migrated to the `reporting` package roadmap as `AC-reporting.package-notes.1-3`; the frontend row below stays here. Migration closeout continuation, #1663 / #1716.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.12.3 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.6`, #1821 Wave B)

### AC5.13: Personal Report Package Traceability Appendix

Issue [#572](https://github.com/wangzitian0/finance_report/issues/572)
supplies the package-specific source-ledger-report traceability appendix. The
appendix does not replace the existing report calculations; it exposes the
traceability anchors, explicit unavailable/not-applicable states, review state,
confidence tier, and completeness warning taxonomy that package consumers need
to audit each report line.

> *(AC5.13.1 removed and AC5.13.2 removed and AC5.13.4 removed and AC5.13.5 removed — migrated to the `reporting` package roadmap as `AC-reporting.package-traceability.1-4`; the frontend row below stays here. Migration closeout continuation, #1663 / #1716.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.13.3 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.7`, #1821 Wave B)

### AC5.14: Framework Policy Result Consumption

EPIC-005 assembles report packages from framework policy results owned by
[EPIC-020](EPIC-020.framework-aware-personal-reporting.md). It renders
statements, notes, exports, and traceability; it must not own US/HK
recognition, measurement, or classification rules.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
> (AC5.14.1 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.framework-neutrality.2`, #1821 Wave A)

### AC5.15: Backend Reporting Integration Journey

Issue [#341](https://github.com/wangzitian0/finance_report/issues/341)
requested a T6 reporting proof. Reporting ownership is EPIC-005 in this
repository; EPIC-006 remains the AI advisor surface. This AC provides the
backend Tier-1 integration proof for the multi-currency reporting cycle without
changing the later PDF export scope tracked by
[#205](https://github.com/wangzitian0/finance_report/issues/205).

> This group's row removed — migrated to the `reporting` package roadmap as
> `AC-reporting.integration.1` (migration closeout continuation, #1663 /
> #1716).

### AC5.16: Report Trust Signals and Restricted-Asset Defaults

The June 2026 UI/report audit found that core report pages were technically
covered but did not render important trust signals already present in backend
payloads. This group makes report default semantics and partial-data warnings
visible to users.

> *(AC5.16.4 removed — migrated to the `reporting` package roadmap as `AC-reporting.trust-signals.3`; AC5.16.1-2's backend halves migrated as `AC-reporting.trust-signals.1-2` while their frontend proofs stay in the rows below. Migration closeout continuation, #1663 / #1716.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.16.1 removed and AC5.16.2 removed and AC5.16.3 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.8` through `.10`, #1821 Wave B)

### AC5.17: Authenticated Report CSV Exports

The report export workflow must preserve the authenticated API boundary and
support every first-class financial statement page that exposes an export
action.

| AC | Acceptance Criteria | Test(s) | File(s) | Priority |
|----|--------------------|---------|---------|----------|
(AC5.17.1 removed, canonical: its backend export half migrated to the `reporting` package roadmap as `AC-reporting.csv-export.1` (migration closeout continuation, #1663 / #1716) and its frontend apiDownload proof migrated to the `meta` package roadmap as `AC-meta.fe-http-client.21`, #1821 Wave B)
(AC5.17.2 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.11`, #1821 Wave B)

### AC5.18: Per-Node Confidence Tier on Balance-Sheet Payloads

Axiom B makes confidence a first-class, measured property. Each balance-sheet
line carries the confidence tier of its contributing ledger facts, and the Net
Worth aggregate rolls up to the worst-input tier (see
[confirmation-workflow.md](../../common/extraction/confirmation-workflow.md) → Confidence Tier
Rollup) — a defined rollup, not an invented number. Income statement, cash flow,
and the monthly cards are a follow-up; provenance (#888) is the co-equal sibling axis.

> This superseded source-type confidence group was removed by the reporting
> package authority cutover (#567). It is not a package readiness or trust
> authority.

### AC5.19: Report Package Snapshot Artifact

The personal financial-report package must be a durable artifact, not only a
live page assembled from current endpoints. Snapshot generation freezes the
period, currency, selected framework, readiness state, source anchors,
traceability lines, and section payloads so the user can reopen and export the
same package after later ledger or market-data changes.

> *(AC5.19.1 removed and AC5.19.2 removed and AC5.19.3 removed — migrated to the `reporting` package roadmap as `AC-reporting.package-snapshot.1-3`; the frontend row below stays here. Migration closeout continuation, #1663 / #1716.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.19.4 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.12`, #1821 Wave B)

### AC5.20: Year-Scale Reporting Validation ([#951](https://github.com/wangzitian0/finance_report/issues/951))

> This group's row removed — migrated to the `reporting` package roadmap as
> `AC-reporting.year-scale.1` (migration closeout continuation, #1663 /
> #1716).

### AC5.32: Income Module Typed Currency + Typed-Intermediate Response ([#1009](https://github.com/wangzitian0/finance_report/issues/1009))

Tech-debt hardening of `apps/backend/src/routers/income.py` (Tier 3 of #1000):
replace soft `str` currency handling with a shared validated/normalized
`CurrencyCode` type, build the response from a typed intermediate
(`AnnualizedIncomeTotals`) instead of a string-keyed dict, and declare an
explicit FX-failure response model. Monetary values stay `Decimal`.

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.income-typed.1-6` (migration closeout continuation, #1663 /
> #1716).

### AC5.33: Report Page Shell + Toolbar Primitives ([#751](https://github.com/wangzitian0/finance_report/issues/751))

Slice 3 of the frontend reuse architecture (#751). Extract the repeated
report-route boilerplate (header, AI-interpretation / home / CSV-export toolbar,
loading skeleton, error+retry state) into shared composition primitives
(`ReportPageShell`, `ReportToolbar`, `AiPromptAction`) so report routes stay thin
and behavior is identical across balance-sheet, income-statement, and cash-flow.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.33.1 removed and AC5.33.2 removed and AC5.33.3 removed and AC5.33.4 removed and AC5.33.5 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.13` through `.17`, #1821 Wave B)

### AC5.34: Report Filter Controls + Filter Hook ([#751](https://github.com/wangzitian0/finance_report/issues/751))

Slice 3 of #751. Provide reusable date and currency filter controls plus a
`useReportFilters` query-layer hook that owns the filter state and derives the
query string, CSV export path, and AI-prompt text so route pages only express
page-level intent.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.34.1 removed and AC5.34.2 removed and AC5.34.3 removed and AC5.34.4 removed and AC5.34.5 removed and AC5.34.6 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.18` through `.23`,
#1821 Wave B)

### AC5.35: Dashboard Aggregation Moved Into Hook Layer ([#751](https://github.com/wangzitian0/finance_report/issues/751))

Slice 3 of #751. Move the dashboard's parallel API aggregation and report
normalization out of the route page and into a `useDashboardData` hook (over the
shared `apiFetch` transport), so the home route composes data instead of
fetching and normalizing it inline. Monetary values stay decimal strings.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
(AC5.35.1 removed and AC5.35.2 removed and AC5.35.3 removed and AC5.35.4 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.24` through `.27`, #1821 Wave B)

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

- [schema.md](../../common/meta/schema.md) - Account and journal entry tables
- [reporting.md](../../common/reporting/reporting.md) - Report calculation rules
- [market_data.md](../../common/pricing/market_data.md) - Exchange rate data source (pre-migration; internalizes into the `pricing` package, #1610)

---

## 🔗 Deliverables

- [x] `apps/backend/src/reporting/extension/` - reporting engine (moved from `src/services/reporting.py` in the reporting package cutover, #1648)
- [x] `apps/backend/src/pricing/extension/fx.py` (moved from `src/services/fx.py` in #1610)
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
  package-level document/export contract and stable section IDs now embedded
  in `PersonalReportPackageDocument`.
- [#564](https://github.com/wangzitian0/finance_report/issues/564) supplies the
  investment performance schedule input from EPIC-017.
- [#566](https://github.com/wangzitian0/finance_report/issues/566) supplies the
  embedded annualized income and long-term compensation section from EPIC-011.
- [#571](https://github.com/wangzitian0/finance_report/issues/571) codifies the
  embedded standards-inspired note and disclosure taxonomy without claiming
  regulated filing compliance.
- [#572](https://github.com/wangzitian0/finance_report/issues/572) defines the
  embedded source-ledger-report traceability appendix.
- [#573](https://github.com/wangzitian0/finance_report/issues/573) supplies the
  representative fixture contract consumed by the package E2E for exact
  Decimal expected outputs.

Closure status:

1. Done: #565 added the behavioral post-merge package journey and provides the
   current baseline proof anchor for
   `personal-financial-report-package` in
   the derived critical-proof matrix (source `common/testing/data/critical-proof-outcomes.yaml`).
2. Done: #570 defines the PackageDocument contract so backend, frontend,
   export, and E2E assertions share stable section IDs, labels, period
   semantics, and Decimal-safe export fields.
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

The macro outcome is `covered` in the derived critical-proof matrix (source `common/testing/data/critical-proof-outcomes.yaml`) once
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

*(AC5.7.1 removed and AC5.7.3 removed — migrated to the `reporting` package roadmap as `AC-reporting.net-worth-timeseries.1-2`, #1821 Wave A)*
(AC5.7.2 removed and AC5.7.4 removed and AC5.7.5 removed and AC5.7.6 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-viz-reports.28` through `.31`, #1821 Wave B)

**Priority**: P1 (high) — needed for vision parity but not blocking user adoption.
**Estimated effort**: 3-5 days backend + 2-3 days frontend.

### AC5.36: Report Snapshots Typed Contract ([#1008](https://github.com/wangzitian0/finance_report/issues/1008))

Tier 2 of #1000. `GET /reports/{report_type}/snapshots` declares a typed
`list[ReportSnapshotSummary]` response (built from the ORM via `from_attributes`
instead of a hand-rolled dict), and `report_type` is typed as the snapshot enum so
an unknown value is rejected with 422 instead of silently returning an empty list.

> This group's rows removed — migrated to the `reporting` package roadmap as
> `AC-reporting.snapshots-typed.1-2` (migration closeout continuation,
> #1663 / #1716).

### AC5.37: Trust-First Reports Cockpit ([#1209](https://github.com/wangzitian0/finance_report/issues/1209))

The Reports landing page must answer whether report output is currently
trustworthy before it presents the report navigation cards. It consumes the
existing package readiness/source-trust contract and does not duplicate
readiness derivation or source-trust rules in the frontend.

The former trust-first cockpit criteria are canonical in the `reporting`
package roadmap as `AC-reporting.fe-viz-reports.32` and `.33`. The latter
directly backs the `non-goals-not-budgeting-app` vision anchor (#1821 Wave B,
#1858).
