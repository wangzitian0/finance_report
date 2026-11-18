# Reports & Dashboards

Finance Report generates deterministic point-in-time and period financial statements ([EPIC-005](../project/EPIC-005.reporting-visualization.md)).

## Personal Report Package

Preview and generate immutable multi-statement packages via:
- Preview: `GET /api/reports/package?framework_id=personal_us_gaap_like` (with paginated drill-downs: `/api/reports/package/line-details`, `/api/reports/package/manifest-entries`, `/api/reports/package/policy-decisions`, `/api/reports/package/cash-flow-events`).
- Generate / reopen / export: `POST /api/reports/package/snapshots`, `GET /api/reports/package/snapshots`, `GET /api/reports/package/snapshots/{snapshot_id}`, `GET /api/reports/package/snapshots/{snapshot_id}/exports?format=json|csv|zip`.

## Statements & Investment Performance

- **Balance Sheet** (`GET /api/reports/balance-sheet`): `Assets - Liabilities = Equity + Net Income`.
- **Income Statement** (`GET /api/reports/income-statement`): `Income - Expenses = Net Income`.
- **Cash Flow Statement** (`GET /api/reports/cash-flow`): Operating, Investing, Financing bridge.
- **Investment Performance (`investment-performance`)**: The `investment_performance` report section consumes `GET /api/portfolio/performance/report-schedule` (`period_start`, `period_end`, `as_of_date`, `currency`), returning Decimal-safe XIRR, time-weighted return, money-weighted return, realized/unrealized P&L, dividend income/yield, holdings, allocation, `data_freshness` (`stale_holdings`), `source_links`, and `notes`.
