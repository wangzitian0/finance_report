# EPIC-017: Investment Portfolio Management (100% Self-Developed)

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-1-portfolio-self-developed`
> **Phase**: 5 (Asset Tracking)
> **Planning estimate**: 6-8 weeks
> **Priority**: P1 (High Priority - Post Two-Stage Review)
> **Dependencies**: EPIC-002 (Double-Entry Core), EPIC-003 (Statement Parsing), EPIC-011 (Asset Lifecycle P0)

---

## 🎯 Objective

Build a **100% self-developed** investment portfolio management system with comprehensive holdings tracking, performance metrics, and brokerage statement auto-parsing. This is a fully integrated, self-hosted solution.

**Core Features**:
- **Holdings Dashboard**: Ticker, quantity, cost basis, market value, P&L
- **Performance Metrics**: XIRR, time-weighted return, money-weighted return
- **Asset Allocation**: Sector, geography, asset class breakdowns
- **Dividend Tracking**: Dividend income, yield calculations
- **Cost Basis Methods**: FIFO, LIFO, Average Cost
- **Brokerage Parsing**: Auto-parse Moomoo, Futu, Interactive Brokers statements

**Out of Scope** (v1):
- Trading execution (buy/sell orders)
- Real-time market data streaming
- Options/futures tracking
- Crypto wallet integration

---

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `investment-performance`
- `annualized-income-long-term`

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Data Model | Extend `atomic_positions` (EPIC-011 Layer 2) for holdings. Use `managed_positions` (Layer 3) for cost basis calculations. |
| 📊 **Accountant** | Accounting Integration | Buy/sell transactions → Journal entries. Realized P&L = Income account. Unrealized P&L = valuation adjustment. |
| 💻 **Developer** | Implementation | Extend extraction service (EPIC-003) for brokerage statements. Reuse market data service for price updates. |
| 🧪 **Tester** | Validation | Test: XIRR calculation accuracy, cost basis methods (FIFO/LIFO/AvgCost), dividend accrual, P&L reconciliation. |
| 📋 **PM** | User Experience | Dashboard = Quick overview. Detail pages for deep-dive. Manual price update UI (user updates every few months). |
| 💹 **Investor** | Domain Expert | XIRR is critical for multi-currency portfolios. Sector allocation helps rebalancing. Dividend tracking for tax reporting. |

---

## Live Status Ownership

This EPIC defines scope and acceptance criteria. Do not use unchecked boxes,
historical audit tables, or planning estimates in this file as current delivery
status. For current proof and delivery state, use:

- Generated AC registry: `docs/ac_registry.yaml`
- AC coverage snapshot: `docs/analysis/test-ac-coverage-report.md`
- Live local proof command: `python tools/analyze_test_ac_coverage.py --stdout`
- North-star tracker: [#444](https://github.com/wangzitian0/finance_report/issues/444)
- Brokerage proof work: [#477](https://github.com/wangzitian0/finance_report/issues/477), [#478](https://github.com/wangzitian0/finance_report/issues/478), [#479](https://github.com/wangzitian0/finance_report/issues/479)

## ✅ Scope Checklist

The checklist below is retained as scope inventory, not as live completion
status. Current implementation proof must come from AC IDs, tests, and tracker
issues.

### Phase 1: Data Model & Holdings Tracking — 2 weeks

#### Data Model (Backend)
- [ ] Extend `atomic_positions` model (EPIC-011 Layer 2)
  - Already exists: `asset_identifier`, `quantity`, `market_value`, `currency`, `broker`
  - Add fields: `asset_type` ENUM (`stock`, `bond`, `etf`, `mutual_fund`)
  - Add fields: `sector` VARCHAR(50), `geography` VARCHAR(50) (for allocation)
- [ ] Extend `managed_positions` model (EPIC-011 Layer 3)
  - Already exists: `quantity`, `cost_basis`, `acquisition_date`, `status`
  - Add fields: `cost_basis_method` ENUM (`FIFO`, `LIFO`, `AvgCost`)
  - Add fields: `unrealized_pnl` DECIMAL(18,2), `realized_pnl` DECIMAL(18,2)
- [ ] Create `dividend_income` table
  - Fields: `id`, `user_id`, `position_id`, `payment_date`, `amount`, `currency`, `type` (ordinary/qualified)
  - Links to `managed_positions`
- [ ] Create `market_data_override` table (for manual price updates)
  - Fields: `id`, `user_id`, `asset_identifier`, `price_date`, `price`, `currency`, `source` (manual/api)
  - Use Case: User updates prices every few months via UI

#### Backend Services
- [ ] `services/portfolio.py` — Portfolio management service
  - [ ] `get_holdings(user_id)` — Get current holdings summary
    - Return: ticker, quantity, cost basis, market value, unrealized P&L
    - Group by account (brokerage)
  - [ ] `calculate_realized_pnl(user_id, date_range)` — Calculate realized P&L
    - Use cost basis method (FIFO/LIFO/AvgCost)
    - Return: list of realized gains/losses
  - [ ] `calculate_unrealized_pnl(user_id, as_of_date)` — Calculate unrealized P&L
    - Market value - cost basis
    - Return: total unrealized gain/loss
  - [ ] `update_market_prices(user_id, price_updates)` — Manual price update
    - Insert into `market_data_override`
    - Recalculate unrealized P&L
- [ ] `services/performance.py` — Performance metrics service
  - [ ] `calculate_xirr(user_id, account_id)` — XIRR calculation
    - Use `scipy.optimize.newton` or `numpy.irr`
    - Return: annualized return (%)
  - [ ] `calculate_time_weighted_return(user_id, date_range)` — TWR calculation
    - Formula: TWR = [(1 + R1) × (1 + R2) × ... × (1 + Rn)] - 1
    - Return: period return (%)
  - [ ] `calculate_money_weighted_return(user_id, date_range)` — MWR calculation
    - Alias for XIRR (IRR of cash flows)
- [ ] `services/allocation.py` — Asset allocation service
  - [ ] `get_sector_allocation(user_id)` — Sector breakdown
    - Return: list of (sector, market_value, percentage)
  - [ ] `get_geography_allocation(user_id)` — Geography breakdown
    - Return: list of (country, market_value, percentage)
  - [ ] `get_asset_class_allocation(user_id)` — Asset class breakdown
    - Return: list of (asset_type, market_value, percentage)

#### API Endpoints
- [ ] `GET /api/portfolio/holdings` — Get holdings summary
- [ ] `GET /api/portfolio/performance` — Get performance metrics (XIRR, TWR, MWR)
- [ ] `GET /api/portfolio/allocation` — Get asset allocation (sector, geography, asset class)
- [ ] `GET /api/portfolio/dividends` — Get dividend income history
- [ ] `POST /api/portfolio/prices/update` — Manual price update
  - Request body: `[{"ticker": "AAPL", "price": 150.00, "date": "2026-02-25"}]`

#### Tests
- [ ] `test_get_holdings()` — Holdings summary with mock data
- [ ] `test_calculate_realized_pnl_fifo()` — FIFO cost basis
- [ ] `test_calculate_realized_pnl_lifo()` — LIFO cost basis
- [ ] `test_calculate_realized_pnl_avgcost()` — Average cost basis
- [ ] `test_calculate_unrealized_pnl()` — Unrealized P&L calculation
- [ ] `test_update_market_prices()` — Manual price update
- [ ] `test_calculate_xirr()` — XIRR accuracy (compare with Excel XIRR)
- [ ] `test_calculate_time_weighted_return()` — TWR calculation
- [ ] `test_get_sector_allocation()` — Sector allocation breakdown

---

### Phase 2: Brokerage Statement Parsing — 2 weeks

#### Backend Services
- [ ] Extend `services/extraction.py` — Add brokerage statement parsing
  - [ ] `parse_moomoo_statement(file_path, user_id)` — Moomoo statement parser
    - Extract: transactions (buy/sell), holdings snapshot, dividends
    - Return: list of `atomic_positions`, `atomic_transactions`
  - [ ] `parse_futu_statement(file_path, user_id)` — Futu statement parser
  - [ ] `parse_interactive_brokers_statement(file_path, user_id)` — IB statement parser
  - [ ] `detect_broker(file_path)` — Auto-detect broker from PDF metadata
    - Check: PDF title, header text, logo
    - Return: broker name (moomoo/futu/ib/unknown)
- [ ] Update `services/processing_account.py` — Handle investment transactions
  - [ ] `process_buy_transaction(txn)` — Create journal entry for stock purchase
    - Debit: Asset:Investment:Securities (increase)
    - Credit: Asset:Cash (decrease)
  - [ ] `process_sell_transaction(txn)` — Create journal entry for stock sale
    - Debit: Asset:Cash (increase)
    - Credit: Asset:Investment:Securities (decrease)
    - Income/Expense: Realized P&L
  - [ ] `process_dividend_transaction(txn)` — Create journal entry for dividend
    - Debit: Asset:Cash (increase)
    - Credit: Income:Dividend (increase)

#### AI Parsing Prompts (Gemini)
- [ ] Create `prompts/brokerage_statement.txt` — Brokerage statement parsing prompt
  - Extract: Account number, period, holdings (ticker, quantity, value), transactions (date, type, ticker, quantity, price)
  - Confidence scoring: High (table extracted), Medium (partial data), Low (manual fallback)
- [ ] Create `prompts/dividend_notice.txt` — Dividend notice parsing prompt
  - Extract: Ticker, payment date, amount per share, total amount

#### API Endpoints
- [ ] `POST /api/statements/upload` — Extend to support brokerage statements
  - Auto-detect broker via `detect_broker()`
  - Route to appropriate parser (moomoo/futu/ib)
- [ ] `GET /api/statements/{id}/holdings` — Get holdings from statement
  - Return: list of holdings extracted from statement

#### Tests
- [ ] `test_parse_moomoo_statement()` — Moomoo statement parsing (use fixture PDF)
- [ ] `test_parse_futu_statement()` — Futu statement parsing
- [ ] `test_parse_interactive_brokers_statement()` — IB statement parsing
- [ ] `test_detect_broker_moomoo()` — Broker detection (Moomoo PDF)
- [ ] `test_detect_broker_futu()` — Broker detection (Futu PDF)
- [ ] `test_process_buy_transaction()` — Buy transaction → journal entry
- [ ] `test_process_sell_transaction()` — Sell transaction → journal entry + realized P&L
- [ ] `test_process_dividend_transaction()` — Dividend transaction → journal entry

---

### Phase 3: Frontend Dashboard & Manual Price UI — 2-3 weeks

#### Frontend UI
- [ ] `/portfolio` — Portfolio Dashboard Page
  - [ ] Holdings table
    - Columns: Ticker, Quantity, Cost Basis, Market Value, Unrealized P&L (%, $)
    - Sortable, searchable
  - [ ] Performance summary cards
    - XIRR, Time-Weighted Return, Money-Weighted Return
    - Period filters: YTD, 1Y, 3Y, All Time
  - [ ] Asset allocation charts
    - Pie chart: Sector allocation
    - Pie chart: Geography allocation
    - Bar chart: Asset class allocation
  - [ ] Dividend income timeline
    - Bar chart: Monthly dividend income (last 12 months)
- [ ] `/portfolio/[ticker]` — Holding Detail Page
  - [ ] Transaction history (buy/sell)
  - [ ] Dividend history
  - [ ] Cost basis breakdown (FIFO/LIFO/AvgCost comparison)
  - [ ] Performance chart (line chart: market value over time)
- [ ] `/portfolio/prices` — Manual Price Update Page
  - [ ] Price entry form
    - Input: Ticker, Price, Date
    - Batch entry: CSV upload support
  - [ ] Current prices table
    - Columns: Ticker, Current Price, Last Update Date, Source (manual/api)
    - Edit inline
  - [ ] Update history log
    - Show: Date, Ticker, Old Price, New Price, Updated By

#### Frontend Components
- [ ] `components/portfolio/HoldingsTable.tsx` — Holdings table component
- [ ] `components/portfolio/PerformanceCard.tsx` — Performance metric card
- [ ] `components/portfolio/AllocationChart.tsx` — Asset allocation pie/bar chart
- [ ] `components/portfolio/DividendTimeline.tsx` — Dividend income chart
- [ ] `components/portfolio/PriceUpdateForm.tsx` — Manual price update form
- [ ] `components/portfolio/TransactionHistory.tsx` — Transaction history list

#### Tests
- [ ] Manual UI test: Portfolio dashboard loads with mock data
- [ ] Manual UI test: Manual price update form submits successfully
- [ ] Manual UI test: Holdings table sorting/filtering
- [ ] Manual UI test: Allocation charts render correctly

---

### Phase 4: Integration & Performance Optimization — 1-2 weeks

#### Backend Optimization
- [ ] Batch price updates — Update multiple tickers in single request
- [ ] Cache allocation results — Redis cache for expensive aggregations
- [ ] Index optimization — Add indexes on `managed_positions.user_id`, `dividend_income.position_id`

#### Data Migration
- [ ] Migrate existing asset data from EPIC-011 to new schema
  - Add `asset_type`, `sector`, `geography` to existing positions
  - Backfill cost basis data

#### Integration Tests
- [ ] `test_end_to_end_buy_sell_cycle()` — Full cycle: upload statement → parse → create journal entries → calculate P&L
- [ ] `test_dividend_accrual_to_income()` — Dividend transaction → journal entry → income statement
- [ ] `test_unrealized_pnl_balance_sheet()` — Unrealized P&L → asset revaluation → balance sheet

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/portfolio/`

### AC17.1: Holdings & P&L Tracking
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.1.1 | Holdings Summary | `test_get_holdings_happy_path` | `portfolio/test_portfolio_service.py` | P0 |
| AC17.1.2 | FIFO Cost Basis | `test_sell_transaction_uses_fifo_and_records_realized_gain` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.1.3 | LIFO Cost Basis | `test_sell_transaction_uses_lifo_loss_and_disposes_position` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.1.4 | Average Cost Basis | `test_sell_transaction_uses_average_cost_for_realized_pnl` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.1.5 | Unrealized P&L Calculation | `test_unrealized_pnl_happy_path` | `portfolio/test_portfolio_service.py` | P0 |
| AC17.1.6 | Manual Price Update | `test_update_prices_happy` | `portfolio/test_portfolio_service.py` | P1 |

### AC17.2: Performance Metrics

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.2.1 | XIRR Accuracy (within 0.01% of Excel) | `test_xirr_with_realistic_data` | `portfolio/test_performance_service.py` | P0 |
| AC17.2.2 | Time-Weighted Return | `test_time_weighted_return_with_period` | `portfolio/test_performance_service.py` | P0 |
| AC17.2.3 | Money-Weighted Return | `test_money_weighted_return_with_data` | `portfolio/test_performance_service.py` | P1 |

### AC17.3: Asset Allocation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.3.1 | Sector Allocation Breakdown | `test_sector_allocation_with_positions` | `portfolio/test_allocation_service.py` | P1 |
| AC17.3.2 | Geography Allocation Breakdown | `test_geography_allocation_with_positions` | `portfolio/test_allocation_service.py` | P1 |
| AC17.3.3 | Asset Class Allocation Breakdown | `test_asset_class_allocation_with_positions` | `portfolio/test_allocation_service.py` | P1 |

### AC17.4: Brokerage Statement Parsing

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.4.1 | Moomoo Statement Parsing | `test_parse_moomoo_fixture_subscription_positions` | `portfolio/test_brokerage_position_parsing.py` | P0 |
| AC17.4.2 | Futu Statement Parsing | `test_parse_futu_fixture_aggregate_position` | `portfolio/test_brokerage_position_parsing.py` | P1 |
| AC17.4.3 | Interactive Brokers Parsing | `test_import_interactive_brokers_positions_idempotently_reconciles` | `portfolio/test_brokerage_position_parsing.py` | P1 |
| AC17.4.4 | Broker Auto-Detection (Moomoo) | `test_detect_broker_moomoo_futu_and_interactive_brokers` | `portfolio/test_brokerage_position_parsing.py` | P1 |
| AC17.4.5 | Broker Auto-Detection (Futu) | `test_detect_broker_moomoo_futu_and_interactive_brokers` | `portfolio/test_brokerage_position_parsing.py` | P1 |
| AC17.4.6 | Brokerage Import Endpoint | `test_brokerage_import_endpoint`, `test_statement_import_flows_to_holdings_and_balance_sheet` | `portfolio/test_brokerage_position_parsing.py` | P1 |
| AC17.4.7 | Upload Parse-to-Import Bridge | `test_parse_statement_background_imports_brokerage_positions`, `test_parse_document_routes_brokerage_balance_mismatch_to_parsed` | `extraction/test_statement_brokerage_import_bridge.py` | P0 |

### AC17.5: Investment Accounting (Journal Entries)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.5.1 | Buy Transaction → Journal Entry | `test_buy_transaction_creates_balanced_journal_entry_and_lot` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.5.2 | Sell Transaction → Journal Entry + Realized P&L | `test_sell_transaction_uses_fifo_and_records_realized_gain`, `test_sell_transaction_uses_average_cost_for_realized_pnl` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.5.3 | Dividend → Journal Entry → Income Statement | `test_dividend_transaction_posts_income_and_dividend_record` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.5.4 | Unrealized P&L → Balance Sheet | `test_unrealized_pnl_happy_path`, `test_statement_import_flows_to_holdings_and_balance_sheet` | `portfolio/test_portfolio_service.py`, `portfolio/test_brokerage_position_parsing.py` | P0 |

### AC17.6: Integration & End-to-End

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.6.1 | Full Buy/Sell Cycle | `test_sell_transaction_uses_fifo_and_records_realized_gain` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.6.2 | Dividend Accrual to Income | `test_dividend_transaction_posts_income_and_dividend_record` | `portfolio/test_investment_accounting.py` | P0 |

### AC17.8: Brokerage Import Completion UI

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.8.1 | Import to Portfolio button visible for parsed/approved statements | `AC17.8.1 shows Import to Portfolio button for parsed statement` | `frontend/src/__tests__/statementDetailPage.coverage.test.tsx` | P0 |
| AC17.8.2 | Import result banner with stats and portfolio link shown on success | `AC17.8.2 shows import result banner and portfolio link on success` | `frontend/src/__tests__/statementDetailPage.coverage.test.tsx` | P0 |
| AC17.8.3 | Import failure shows actionable error without sensitive data | `AC17.8.3 shows actionable import error banner without exposing sensitive data` | `frontend/src/__tests__/statementDetailPage.coverage.test.tsx` | P0 |
| AC17.8.4 | Portfolio page shows total portfolio value prominently after import | `AC17.8.4 shows total portfolio value banner when active holdings are loaded` | `frontend/src/__tests__/portfolioPage.test.tsx` | P0 |
| AC17.8.5 | Import button hidden for non-parsed/approved statements (partial batch) | `AC17.8.5 does not show Import to Portfolio for non-parsed statements` | `frontend/src/__tests__/statementDetailPage.coverage.test.tsx` | P0 |

### AC17.9: Point-in-Time Portfolio Snapshots

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.9.1 | Historical holdings quantity and market value come from the latest AtomicPosition snapshot at or before `as_of_date` | `test_get_holdings_explicit_as_of_uses_historical_atomic_snapshot` | `portfolio/test_portfolio_service.py` | P0 |
| AC17.9.2 | Portfolio holdings API returns date-bounded snapshot quantities for explicit `as_of_date` requests | `test_get_holdings_explicit_date_uses_historical_snapshot_quantity` | `portfolio/test_portfolio_router.py` | P0 |
| AC17.9.3 | Portfolio page exposes an as-of date selector and passes it to `/api/portfolio/holdings` | `AC17.9.3 passes selected as-of date to holdings API` | `frontend/src/__tests__/portfolioPage.test.tsx` | P0 |

### AC17.10: Investment Performance Report Schedule API

This API contract is the EPIC-017-owned schedule input for the personal
financial-report package tracked by #564. It is intentionally separate from
the dashboard-only `/api/portfolio/performance` summary so EPIC-005 can consume
a stable, report-ready payload with source traceability and explanation fields.

Endpoint:
`GET /api/portfolio/performance/report-schedule?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD&as_of_date=YYYY-MM-DD&currency=SGD`

When dates are omitted, the API defaults to year-to-date reporting using
`period_end=today`, `period_start=January 1` of the period-end year, and
`as_of_date=period_end`.

Response object:

| Field | Meaning |
|---|---|
| `period_start`, `period_end`, `as_of_date`, `currency` | Schedule boundary and presentation currency |
| `xirr`, `time_weighted_return`, `money_weighted_return` | Portfolio performance metrics as percentages |
| `realized_pnl`, `unrealized_pnl`, `dividend_income`, `dividend_yield` | Decimal-safe return components |
| `holdings` | Per holding `{asset_identifier, quantity, cost_basis, market_value, unrealized_pnl, realized_pnl, dividend_income, currency}` rows |
| `allocation` | Sector, geography, and asset-class allocation rows |
| `data_freshness` | Market-data source, latest price date, stale flag, and manual override basis |
| `source_links` | Source document, brokerage import, price source, and ledger/report traceability anchors |
| `notes` | Human-readable methods and limitations for cost basis, market prices, and return metrics |

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.10.1 | Investment performance schedule API exposes report-ready metrics and rows | `test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule`; `test_personal_financial_report_package_post_merge_journey`; `test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract` | `apps/backend/tests/portfolio/test_portfolio_router.py`; `tests/e2e/test_personal_financial_report_package.py`; `tests/tooling/test_investment_performance_report_contract.py` | P0 |
| AC17.10.2 | Investment performance schedule API exposes data freshness, source links, and notes for report traceability | `test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule`; `test_personal_financial_report_package_post_merge_journey`; `test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract` | `apps/backend/tests/portfolio/test_portfolio_router.py`; `tests/e2e/test_personal_financial_report_package.py`; `tests/tooling/test_investment_performance_report_contract.py` | P0 |

### AC17.11: Portfolio Financial Logic Audit Fixes

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.11.1 | Portfolio XIRR and MWR use investment transactions only, excluding unrelated bank atomic transactions | `test_AC17_11_1_xirr_excludes_unrelated_bank_transactions()` | `portfolio/test_financial_logic_audit.py` | P0 |
| AC17.11.2 | Portfolio summary YTD realized P&L and dividend income are converted to presentation currency before aggregation | `test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency()` | `portfolio/test_financial_logic_audit.py` | P0 |
| AC17.11.3 | Portfolio TWR excludes unrelated bank atomic transactions from period cash-flow adjustment | `test_AC17_11_3_twr_excludes_unrelated_bank_transactions()` | `portfolio/test_financial_logic_audit.py` | P0 |

### Brokerage PDF to Asset Report Proof Matrix

This is the detailed EPIC-017 counterpart to the README core proof path. It
keeps the product path, EPIC ownership, AC ownership, executable proof, and CI
tier in one place for the Moomoo/Futu brokerage PDF to asset report journey.
EPIC-008 remains the owner of the provider-backed staging AI/OCR gate.

| Product path step | EPIC owner | AC owner | Executable proof | File | CI tier |
|---|---|---|---|---|---|
| Upload Moomoo/Futu brokerage PDF through `/api/statements/upload` | EPIC-008 / EPIC-013 | AC8.13.10 | `test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | Post-merge staging AI/OCR gate |
| Background parse detects brokerage payload and imports positions without a manual API call | EPIC-017 | AC17.4.7 / AC17.5.4 / AC8.13.10 | `test_parse_statement_background_imports_brokerage_positions` | `apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py` | Backend shard |
| Brokerage-style OCR balance mismatches remain parsed and visible instead of stalling | EPIC-008 / EPIC-017 | AC8.13.10 | `test_parse_document_routes_brokerage_balance_mismatch_to_parsed` | `apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py` | Backend shard |
| Statement-scoped import creates holdings | EPIC-017 | AC17.4.6 / AC8.13.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| Imported holdings affect balance sheet value | EPIC-005 / EPIC-017 | AC17.5.4 / AC8.13.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| User completes import and navigates to portfolio value | EPIC-017 | AC17.8.1 / AC17.8.2 / AC17.8.4 | `AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation` | `apps/frontend/src/__tests__/brokerageImportCompletionFlow.test.tsx` | Frontend test |

Provider-backed gate details live in
[EPIC-008](EPIC-008.testing-strategy.md#tier-3-e2e-implementation) and
[CI/CD SSOT](../ssot/ci-cd.md#post-merge-staging-aiocr-gate). The README keeps
the compact entry-point version of this matrix.

### Personal Report Package Dependency

[#564](https://github.com/wangzitian0/finance_report/issues/564) delivered the
investment performance schedule proof path needed by the personal
financial-report package tracked in
[#563](https://github.com/wangzitian0/finance_report/issues/563). This EPIC
supplies holdings, cost basis, realized and unrealized P&L, dividends,
allocation, and as-of valuation schedules in a form that EPIC-005 consumes as
the `investment_performance` section.
[#596](https://github.com/wangzitian0/finance_report/issues/596) owns the
proof-status promotion after #594.

For #521 closure, this EPIC should be sequenced as:

1. Consume the package section contract from `#570`.
2. Done: finalize the investment-performance inputs and schedule (`#564`).
3. Land supporting explanation assets:
   - report notes (`#571`)
   - traceability appendix (`#572`)
4. Provide deterministic fixture inputs for the package proof (`#573`).
5. Done: extend the implemented `#565` post-merge package proof with the
   report-ready investment schedule (`AC5.8.1`, `AC17.10.1`, `AC17.10.2`).

The post-merge proof test is owned by EPIC-008.

**Traceability Result**:
- Total AC IDs: 27
- Requirements converted to AC IDs: 100% (EPIC-017 Must Have checklist)
- Requirements with test references: 100% (some TBD — tests to be implemented)
- Test files: 4 implemented (`test_portfolio_service.py`, `test_performance_service.py`, `test_allocation_service.py`, `test_investment_accounting.py`); remaining brokerage/parser coverage lives in dedicated parsing and bridge tests.

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **XIRR calculation accuracy within 0.01%** | AC17.2.1: `test_calculate_xirr` | 🔴 Critical |
| **Cost basis methods (FIFO/LIFO/AvgCost) accurate** | AC17.1.2–AC17.1.4 | 🔴 Critical |
| **Brokerage statements auto-parsed (Moomoo, Futu, IB)** | AC17.4.1–AC17.4.3 | Required |
| **Manual price update UI functional** | AC17.1.6: `test_update_market_prices` | Required |
| **Holdings dashboard shows real-time P&L** | AC17.6.1: `test_end_to_end_buy_sell_cycle` | Required |
| **Dividend income → journal entry → income statement** | AC17.5.3, AC17.6.2 | Required |
| **Asset allocation charts accurate** | AC17.3.1–AC17.3.3 | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| **CSV export for holdings** | API endpoint | ⏳ |
| **Mobile-responsive dashboard** | Responsive design | ⏳ |
| **Sector/geography auto-classification (ML)** | AI service | ⏳ |
| **Real-time price API integration** | Market data API (Alpha Vantage, Yahoo Finance) | ⏳ |

### 🚫 Not Acceptable

- XIRR calculation error > 0.1% (indicates formula bug)
- Cost basis calculation wrong (causes P&L errors)
- Brokerage statements not parsed (manual entry required)
- Holdings dashboard stale (prices not updated)
- Unrealized P&L not reflected in balance sheet (accounting equation violation)

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) — `atomic_positions`, `managed_positions`, database models
- [accounting.md](../ssot/accounting.md) — Journal entry rules for investment transactions
- [extraction.md](../ssot/extraction.md) — Statement parsing patterns (extend for brokerage)
- [vision.md](../../vision.md) Decision 1 — Portfolio management strategy (updated to 100% self-developed)

---

## 🔗 Deliverables

### Backend
- [ ] `apps/backend/src/models/portfolio.py` — Portfolio models (extend `atomic_positions`, `managed_positions`)
- [ ] `apps/backend/src/models/dividend.py` — Dividend income model
- [ ] `apps/backend/src/services/portfolio.py` — Holdings, P&L calculations
- [ ] `apps/backend/src/services/performance.py` — XIRR, TWR, MWR calculations
- [ ] `apps/backend/src/services/allocation.py` — Asset allocation service
- [ ] `apps/backend/src/services/extraction.py` — Extend with brokerage parsers
- [ ] `apps/backend/src/routers/portfolio.py` — Portfolio API endpoints
- [ ] `apps/backend/tests/portfolio/` — Test suite
  - `test_portfolio_service.py`
  - `test_performance_metrics.py`
  - `test_allocation_service.py`
  - `test_brokerage_parsing.py`
  - `test_cost_basis_methods.py`

### Frontend
- [ ] `apps/frontend/src/app/(main)/portfolio/page.tsx` — Portfolio dashboard
- [ ] `apps/frontend/src/app/(main)/portfolio/[ticker]/page.tsx` — Holding detail page
- [ ] `apps/frontend/src/app/(main)/portfolio/prices/page.tsx` — Manual price update page
- [ ] `apps/frontend/src/components/portfolio/` — Portfolio components
  - `HoldingsTable.tsx`
  - `PerformanceCard.tsx`
  - `AllocationChart.tsx`
  - `DividendTimeline.tsx`
  - `PriceUpdateForm.tsx`

### Documentation
- [x] `docs/ssot/extraction.md` — Statement parsing SSOT covers brokerage upload/parse/import routing
- [x] `README.md` — Core proof path matrix links brokerage PDF upload to asset report AC/test/CI proof

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| Real-time market data API | P2 | v2.0 (Alpha Vantage, Yahoo Finance integration) |
| Options/futures tracking | P3 | v2.0 (complex derivatives support) |
| Tax-loss harvesting | P3 | v2.0 (tax optimization features) |
| Sector/geography auto-classification | P2 | v2.0 (ML-based classification) |

---

## 🐛 Known Issues & Gaps

- [ ] **Manual Price Update Frequency**: User must update prices manually. Real-time API integration deferred to v2.0.
- [ ] **Brokerage Statement Coverage**: Only Moomoo, Futu, IB supported in v1. Other brokers require manual entry.
- [ ] **Cost Basis Edge Cases**: Complex scenarios (stock splits, mergers) not handled in v1.
- [ ] **Multi-Currency XIRR**: XIRR calculation assumes single currency. Multi-currency portfolios require FX conversion.

---

## ❓ Q&A (Clarification Required)

### Q1: Portfolio feature scope — Confirmed by user
> **Question**: Should v1 include all metrics (XIRR, TWR, MWR, sector allocation, dividends)?  
> **Impact**: Backend service scope  
> **User Answer**: "Full-featured" (implement all metrics)  
> **Decision**: ✅ Full scope in v1: XIRR, TWR, MWR, sector allocation, geography allocation, dividend tracking, cost basis methods.

### Q2: Market data source — Confirmed by user
> **Question**: Should v1 use real-time API (Alpha Vantage, Yahoo Finance) or manual entry?  
> **Impact**: Market data service design  
> **User Answer**: "搞个 UI 维护吧，这类基本上就是几个月改一次而已" (Manual UI, updated every few months)  
> **Decision**: ✅ Manual price update UI in v1. Real-time API deferred to v2.0.

### Q3: Brokerage statement parsing — Confirmed by user
> **Question**: Should brokerage statements be uploaded like bank statements?  
> **Impact**: Extraction service extension  
> **User Answer**: "也是上传 statement 吧，自动解析" (Upload statements, auto-parse)  
> **Decision**: ✅ Extend EPIC-003 extraction service to support Moomoo, Futu, Interactive Brokers statements.

### Q4: Cost basis method preference
> **Question**: Should users choose cost basis method (FIFO/LIFO/AvgCost) per account or globally?  
> **Impact**: `managed_positions` model (account-level vs user-level setting)  
> **Status**: ⏳ Pending user clarification

### Q5: Unrealized P&L accounting treatment
> **Question**: Should unrealized P&L be reflected in balance sheet immediately, or only on statement date?  
> **Impact**: Asset revaluation journal entry timing  
> **Status**: ⏳ Pending user clarification

### Q6: Dividend tax withholding
> **Question**: Should dividend income be recorded gross (before tax) or net (after withholding)?  
> **Impact**: `dividend_income` model, journal entry  
> **Status**: ⏳ Pending user clarification

---

## 📅 Roadmap Snapshot

This is the original planning sequence. It is not a live schedule or current
delivery status table.

| Phase | Content | Planning Estimate |
|------|------|----------|
| **Phase 1** | Data Model & Holdings Tracking | 2 weeks |
| Week 1 | Extend models, create portfolio service | |
| Week 2 | Performance metrics, allocation service, API endpoints | |
| **Phase 2** | Brokerage Statement Parsing | 2 weeks |
| Week 3 | Extend extraction service (Moomoo, Futu, IB parsers) | |
| Week 4 | Processing account integration, tests | |
| **Phase 3** | Frontend Dashboard & Manual Price UI | 2-3 weeks |
| Week 5 | Portfolio dashboard, holdings table | |
| Week 6 | Allocation charts, dividend timeline | |
| Week 7 | Manual price update page, holding detail page | |
| **Phase 4** | Integration & Performance Optimization | 1-2 weeks |
| Week 8 | Batch optimization, caching, migration | |

**Total Estimate**: 6-8 weeks (depends on clarification response time)

---

## 🔄 Related EPICs

- **EPIC-002**: Double-Entry Core → Journal entries for investment transactions
- **EPIC-003**: Statement Parsing → Extend for brokerage statements
- **EPIC-011**: Asset Lifecycle → `atomic_positions`, `managed_positions` data model foundation
- **EPIC-005**: Reporting → Unrealized P&L in balance sheet, realized P&L in income statement

---

## 📊 Success Metrics (Post-Launch)

- **Brokerage Statement Parsing Accuracy**: ≥ 95% (holdings, transactions, dividends extracted correctly)
- **XIRR Calculation Accuracy**: Within 0.01% of Excel XIRR
- **Holdings Dashboard Load Time**: < 2s (with 1000+ holdings)
- **Manual Price Update Frequency**: User updates prices ≤ 1x per month (low-frequency, high-value)
- **User Adoption**: ≥ 80% of users with investment accounts use portfolio dashboard

---

*Planning snapshot captured: February 2026*


---

## 🔍 Historical FE/UI Audit Snapshot (April 2026)

> Audit Date: 2026-04-06 | Auditor: AI Agent (Sisyphus) | Scope: Frontend completeness, UX quality, accessibility
>
> Snapshot note: this audit records findings from April 2026. Treat file and
> implementation inventories as historical context unless re-validated against
> the current tree and generated proof reports.

### Executive Summary

**Backend at audit time**: ✅ **FULLY IMPLEMENTED** (1,226 lines across 3 services + 234 lines router + 104 lines schemas)
- `portfolio.py` (628 lines) — Holdings CRUD, P&L calculations, price updates
- `performance.py` (413 lines) — XIRR, TWR, MWR calculations
- `allocation.py` (183 lines) — Sector/geography/asset class allocation
- `portfolio router` (234 lines) — All API endpoints operational
- `portfolio schemas` (104 lines) — Pydantic request/response models
- **Test coverage**: 1,780 lines, 64 test functions across 4 test files

**Frontend at audit time**: ❌ **NOT IMPLEMENTED** — The portfolio frontend was missing in the audited tree. Only `/assets` page from EPIC-011 existed, which was a basic position tracker and did not fulfill EPIC-017 requirements.

### Inventory: What Exists

| File | Lines | Purpose | Covers EPIC-017? |
|------|-------|---------|-----------------|
| `assets/page.tsx` | 280 | Position tracker from EPIC-011: KPI cards (Total Positions, Active Holdings, Total Cost Basis), currency allocation bar, grouped by broker, status filters | ⚠️ Partial — shows basic holdings but lacks performance metrics, market value, P&L, allocation charts, dividends |
| `components/charts/PieChart.tsx` | 94 | Generic SVG donut chart | 🛠️ Reusable for allocation |
| `components/charts/TrendChart.tsx` | 95 | Generic SVG line/area chart | 🛠️ Reusable for performance over time |
| `components/charts/BarChart.tsx` | 55 | Generic SVG bar chart | 🛠️ Reusable for dividend timeline |
| `components/charts/SankeyChart.tsx` | 186 | ECharts sankey (cash flow) | ❌ Not relevant |
| `Sidebar.tsx` line 39 | — | "Portfolio" nav item points to `/assets`, not `/portfolio` | ⚠️ Wrong route |

### Gap Analysis

#### 🔴 Critical Gaps (entire feature missing)

| # | Gap | EPIC Requirement | Status |
|---|-----|-----------------|--------|
| G1 | **No `/portfolio` route at audit time** | EPIC Phase 3 specifies `/portfolio` dashboard page, `/portfolio/[ticker]` detail page, `/portfolio/prices` price update page | `apps/frontend/src/app/(main)/portfolio/` directory did not exist in the audited tree. |
| G2 | **No portfolio components at audit time** | EPIC specifies `HoldingsTable.tsx`, `PerformanceCard.tsx`, `AllocationChart.tsx`, `DividendTimeline.tsx`, `PriceUpdateForm.tsx`, `TransactionHistory.tsx` | `apps/frontend/src/components/portfolio/` directory did not exist in the audited tree. |
| G3 | **No portfolio API client functions** | Backend exposes `/api/portfolio/holdings`, `/api/portfolio/performance`, `/api/portfolio/allocation`, `/api/portfolio/prices` | `lib/api.ts` has zero portfolio-specific functions. `lib/types.ts` has only `ManagedPosition` from EPIC-011, no portfolio response types. |
| G4 | **No performance metrics display** | XIRR, TWR (Time-Weighted Return), MWR (Money-Weighted Return) — core portfolio feature | No UI anywhere shows these calculations. Backend computes them; frontend does not consume them. |
| G5 | **No market value or P&L display** | Current holdings should show: Market Value, Unrealized P&L, Realized P&L | `/assets` page shows only Cost Basis (book value). No market value column, no P&L. |
| G6 | **No allocation charts** | Sector, geography, asset class breakdown with pie/donut charts | No portfolio-specific charts. Generic `PieChart.tsx` exists and is reusable, but no page or component consumes it for allocation data. |
| G7 | **No dividend tracking UI** | Dividend timeline, yield calculations, ex-date tracking | Zero implementation. |
| G8 | **No market price update page** | Manual price update form (user updates prices monthly) | Zero implementation. Backend has `POST /api/portfolio/prices` endpoint ready. |
| G9 | **No holding detail page** | `/portfolio/[ticker]` with transaction history, performance chart, cost basis breakdown | Zero implementation. |
| G10 | **No frontend tests** | EPIC requires frontend test coverage for portfolio features | Zero portfolio frontend tests (backend has 64 test functions). |

#### 🟡 Important Gaps (existing `/assets` page shortcomings)

| # | Gap | Detail |
|---|-----|--------|
| G11 | **Sidebar routing mismatch** | "Portfolio" nav item routes to `/assets` instead of `/portfolio`. When portfolio pages are built, this needs updating. |
| G12 | **`/assets` page uses wrong API** | Calls `/api/assets/positions` (EPIC-011) instead of `/api/portfolio/holdings` (EPIC-017). Different data shape — positions vs holdings with market data. |
| G13 | **No cost basis method selection** | EPIC-017 supports FIFO/LIFO/AvgCost. `/assets` page shows a single cost basis number with no method indicator or toggle. |
| G14 | **Currency allocation bar is custom, not chart component** | `/assets` builds its own allocation bar instead of using the generic `PieChart.tsx`. Inconsistent with design system. |

### What Can Be Reused

The project has chart infrastructure and design patterns ready for portfolio features:

| Asset | Reusable For |
|-------|-------------|
| `PieChart.tsx` (94 lines) | Allocation breakdown (sector, geography, asset class) |
| `TrendChart.tsx` (95 lines) | Performance over time (XIRR trend, NAV history) |
| `BarChart.tsx` (55 lines) | Dividend timeline (monthly/quarterly bars) |
| `lib/api.ts` wrapper | All portfolio API calls (just add typed functions) |
| CSS design tokens | `--chart-1` through `--chart-5` palette, `.card`, `.badge-*`, `.page-header` |
| `ConfirmDialog`, `Sheet`, `Toast` | UI primitives for price update confirmation, holding detail panel, success/error feedback |
| `@tanstack/react-query` | Already installed, used by `/assets` page. Use for portfolio data fetching. |
| `decimal.js` | Already installed. Use for frontend P&L display precision. |

### Recommendations (Priority Order)

1. **[P0] Create `/portfolio` route with holdings dashboard** — This is the single highest-impact deliverable. Show holdings table with columns: Ticker, Name, Quantity, Avg Cost, Market Price, Market Value, Unrealized P&L, P&L %. Consume `GET /api/portfolio/holdings`.
2. **[P0] Add performance summary cards** — Display XIRR, TWR, MWR from `GET /api/portfolio/performance`. Use `PerformanceCard` component with period selector (1M, 3M, 6M, 1Y, YTD, All).
3. **[P0] Add portfolio TypeScript types** — Define `PortfolioHolding`, `PerformanceMetrics`, `AllocationBreakdown`, `DividendRecord`, `PriceUpdate` types in `lib/types.ts` matching backend schemas.
4. **[P1] Build allocation charts page section** — Use existing `PieChart.tsx` to show sector/geography/asset class allocation from `GET /api/portfolio/allocation`.
5. **[P1] Build market price update page** — `/portfolio/prices` with form to update prices. Backend `POST /api/portfolio/prices` is ready.
6. **[P1] Build holding detail page** — `/portfolio/[ticker]` with transaction history, performance chart, cost basis breakdown (FIFO/LIFO/AvgCost toggle).
7. **[P2] Add dividend timeline** — Use `BarChart.tsx` for monthly dividend income visualization.
8. **[P2] Update Sidebar routing** — Change "Portfolio" nav from `/assets` to `/portfolio`. Consider keeping `/assets` as a sub-feature or deprecating it.
9. **[P3] Write frontend tests** — Test holdings table rendering, performance card calculations display, allocation chart data transformation, price update form validation.

### Implementation Estimate

At audit time, the backend appeared complete and chart infrastructure existed, so the frontend build-out was estimated at:

| Phase | Deliverable | Effort |
|-------|------------|--------|
| 1 | Portfolio types + API functions + holdings dashboard | 2-3 days |
| 2 | Performance cards + allocation charts | 1-2 days |
| 3 | Price update page + holding detail page | 2-3 days |
| 4 | Dividend timeline + frontend tests | 1-2 days |
| **Total** | | **6-10 days** |

---

*FE/UI Audit appended: April 2026*

---

## 🆕 UI Gap Audit (April 2026) — Dividends, Cost Basis, Realized P&L Frontend

**Origin**: UI gap audit against [vision.md](../../vision.md) decision 1 (100% self-developed portfolio with XIRR/TWR/MWR, dividend tracking, cost basis methods). Backend portfolio APIs are planned but the frontend has no surfaces for dividend history, cost-basis selection, or realized P&L per holding.

### Acceptance Criteria

- [x] **AC17.7.1** Holding detail page `/portfolio/[ticker]` renders three tabs: `Overview`, `Dividends`, `Realized P&L`
- [x] **AC17.7.2** Dividends tab lists historical dividend events `{ex_date, pay_date, amount, currency, reinvested}` from `GET /api/portfolio/{ticker}/dividends`
- [x] **AC17.7.3** Cost-basis method selector (`FIFO` / `LIFO` / `AvgCost`) on holding detail page persists per-holding via `PATCH /api/portfolio/{ticker}` and re-fetches realized P&L
- [x] **AC17.7.4** Realized P&L tab shows lot-level table `{lot_id, acquired_date, sold_date, quantity, basis, proceeds, gain_loss, holding_period}` from `GET /api/portfolio/{ticker}/realized`
- [x] **AC17.7.5** Portfolio summary card on dashboard adds `realized_pnl_ytd` and `dividend_income_ytd` figures from `GET /api/portfolio/summary`
- [x] **AC17.7.6** Frontend test mounts HoldingDetailPage, switches to Dividends tab, and asserts dividend row labels render

**Priority**: P1 — depends on backend portfolio API delivery; surfaces vision-critical metrics.
**Estimated effort**: 5-7 days frontend (3 tabs + cost-basis selector + summary additions); backend dividend/realized endpoints tracked in core EPIC-017 scope.
