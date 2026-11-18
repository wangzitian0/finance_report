# EPIC-005: Financial Reports & Visualization
<!-- epic-file: goal-stub -->
> **Status**: ✅ Complete — shipped and cut over to the `reporting` package.
> **Vision Anchor**: `non-goals-not-budgeting-app`
> **Goal**: generate standard financial statements (balance sheet, income statement, cash flow statement) and visualize asset structure and trends. Package specifications live in [`common/reporting/readme.md`](../../common/reporting/readme.md).
This file is a historical goal stub; it defines no AC rows.
## Macro Proof Ownership
- `personal-financial-report-package` - `asset-distribution-net-worth` - `monthly-income-spending` - `investment-performance` - `annualized-income-long-term`
## Framework Policy Result Consumption
EPIC-005 assembles report packages from framework policy results and must not own US/HK recognition, measurement, or classification rules. Integration of EPIC-020 framework policy results is owned at the assembly layer.
## Investment Performance Reporting Schedule
Package consumption of the investment performance schedule (`GET /api/portfolio/performance/report-schedule`, section `investment-performance` / `investment_performance`) includes `source_links` and `notes` report section metadata.
