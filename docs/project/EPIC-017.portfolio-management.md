# EPIC-017: Investment Portfolio Management (100% Self-Developed)

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-1-portfolio-self-developed`
> **Phase**: 5 (Asset Tracking)
> **Planning estimate**: 6-8 weeks
> **Priority**: P1 (High Priority - Post Two-Stage Review)
> **Dependencies**: EPIC-002 (Double-Entry Core), EPIC-003 (Statement Parsing), EPIC-011 (Asset Lifecycle P0)
> **Usable milestone**: ⏸️ deferred (post-Usable). Investment portfolio is owned here but **not** required for the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1) (upload a year of real data on prod).

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

- Generated AC registry index: `docs/ac_registry.yaml`
- Live local proof command: `python tools/analyze_test_ac_coverage.py --no-write --stdout`
- CI proof artifact: `ac-test-traceability-audit`
- North-star tracker: [#444](https://github.com/wangzitian0/finance_report/issues/444)
- Brokerage proof work: [#477](https://github.com/wangzitian0/finance_report/issues/477), [#478](https://github.com/wangzitian0/finance_report/issues/478), [#479](https://github.com/wangzitian0/finance_report/issues/479)

## Scope Management

This EPIC owns portfolio scope and AC definitions. Detailed implementation
inventories were removed because models, APIs, frontend components, and tests are
now better managed by code, SSOT files, and generated proof.

| Scope area | Owner |
|---|---|
| Holdings, cost basis, P&L, allocation, dividends | `apps/backend/src/services/portfolio.py`, `apps/backend/src/services/performance.py`, portfolio tests |
| Brokerage statement parsing and import bridge | [extraction.md](../ssot/extraction.md), extraction/portfolio tests |
| Asset and atomic-position model rationale | [assets.md](../ssot/assets.md), [schema.md](../ssot/schema.md) |
| Portfolio API surface | `apps/backend/src/routers/portfolio.py`, API contract tests |
| Portfolio UI surfaces | `apps/frontend/src/app/(main)/portfolio`, frontend tests |
| Current proof and execution stage | AC registries, `tools/check_ac_traceability.py`, [test-execution-matrix.yaml](../ssot/test-execution-matrix.yaml) |

Framework boundary: EPIC-017 supplies portfolio facts, not final framework
accounting conclusions. Holdings, lots, cost basis, dividends, fees, prices,
freshness, and source links are inputs to EPIC-020. Whether a US-like or HK-like
personal report presents a valuation change in a specific statement line or
disclosure belongs to EPIC-020 and EPIC-005 assembly.

Future scope such as additional brokers, complex corporate actions, options,
futures, crypto, and real-time market streaming needs explicit ACs before it can
be treated as current work.

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
| AC17.1.7 | Portfolio summary happy path returns correct counts and totals. | `test_portfolio_summary_happy` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.1.8 | Summary includes both active and disposed positions. | `test_portfolio_summary_with_disposed` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.1.9 | Zero total cost -> net_pnl_percent = 0. | `test_portfolio_summary_zero_cost` | `portfolio/test_portfolio_service.py` | P1 |

### AC17.2: Performance Metrics

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.2.1 | XIRR Accuracy (within 0.01% of Excel) | `test_xirr_with_realistic_data` | `portfolio/test_performance_service.py` | P0 |
| AC17.2.2 | Time-Weighted Return | `test_time_weighted_return_with_period` | `portfolio/test_performance_service.py` | P0 |
| AC17.2.3 | Money-Weighted Return | `test_money_weighted_return_with_data` | `portfolio/test_performance_service.py` | P1 |
| AC17.2.4 | Zero cost -> realized_pnl_percent = 0. | `test_realized_pnl_zero_cost` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.2.5 | Disposed position in non-base currency triggers FX conversion. | `test_realized_pnl_fx_conversion` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.2.6 | Unrealized PnL happy path returns correct totals. | `test_unrealized_pnl_happy_path` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.2.7 | Unrealized PnL on empty portfolio raises PortfolioNotFoundError. | `test_unrealized_pnl_no_positions` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.2.8 | Zero cost -> unrealized_pnl_percent in details = 0. | `test_unrealized_pnl_zero_cost` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.2.9 | FX conversion for unrealized PnL. | `test_unrealized_pnl_fx_conversion` | `portfolio/test_portfolio_service.py` | P1 |

### AC17.3: Asset Allocation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.3.1 | Sector Allocation Breakdown | `test_sector_allocation_with_positions` | `portfolio/test_allocation_service.py` | P1 |
| AC17.3.2 | Geography Allocation Breakdown | `test_geography_allocation_with_positions` | `portfolio/test_allocation_service.py` | P1 |
| AC17.3.3 | Asset Class Allocation Breakdown | `test_asset_class_allocation_with_positions` | `portfolio/test_allocation_service.py` | P1 |
| AC17.3.4 | TWR calculates period return within reasonable bounds. | `test_time_weighted_return_with_period` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.5 | MWR raises InsufficientDataError on empty portfolio. | `test_money_weighted_return_insufficient_data` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.6 | MWR calculates money-weighted return for loss scenario. | `test_money_weighted_return_with_data` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.7 | XIRR respects as_of_date parameter. | `test_xirr_with_as_of_date` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.8 | TWR returns zero for same-day period. | `test_time_weighted_return_same_day` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.9 | Performance metrics handle cash-only portfolios. | `test_performance_metrics_with_zero_positions` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.10 | XIRR handles extreme convergence edge cases. | `test_xirr_convergence_edge_case` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.11 | _xirr_bisection raises ValueError when no root exists. | `test_xirr_bisection_no_root_raises` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.12 | _xirr_bisection returns Decimal estimate after max_iter exhaustion. | `test_xirr_bisection_max_iter_returns` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.13 | _xirr_newton falls back to bisection on non-convergence. | `test_xirr_newton_fallthrough_to_bisection` | `portfolio/test_performance_service.py` | P1 |
| AC17.3.14 | XIRRCalculationError raised when Newton and bisection both fail. | `test_xirr_calculation_error_raised` | `portfolio/test_performance_service.py` | P1 |

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
| AC17.4.8 | Concurrent Auto/Manual Brokerage Import Idempotency | `test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import` | `portfolio/test_brokerage_position_parsing.py` | P0 |

### AC17.5: Investment Accounting (Journal Entries)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.5.1 | Buy Transaction → Journal Entry | `test_buy_transaction_creates_balanced_journal_entry_and_lot` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.5.2 | Sell Transaction → Journal Entry + Realized P&L | `test_sell_transaction_uses_fifo_and_records_realized_gain`, `test_sell_transaction_uses_average_cost_for_realized_pnl` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.5.3 | Dividend → Journal Entry → Income Statement | `test_dividend_transaction_posts_income_and_dividend_record` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.5.4 | Unrealized P&L → Balance Sheet | `test_unrealized_pnl_happy_path`, `test_statement_import_flows_to_holdings_and_balance_sheet` | `portfolio/test_portfolio_service.py`, `portfolio/test_brokerage_position_parsing.py` | P0 |
| AC17.5.5 | Quantity == 0 -> return market_value directly. | `test_get_latest_price_zero_quantity` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.5.6 | No price data -> AssetNotFoundError. | `test_get_latest_price_no_data` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.5.7 | _get_latest_atomic returns the most recent snapshot. | `test_get_latest_atomic_returns_latest` | `portfolio/test_portfolio_service.py` | P1 |
| AC17.5.8 | _get_latest_atomic returns None when no snapshots exist. | `test_get_latest_atomic_none` | `portfolio/test_portfolio_service.py` | P1 |

### AC17.6: Integration & End-to-End

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.6.1 | Full Buy/Sell Cycle | `test_sell_transaction_uses_fifo_and_records_realized_gain` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.6.2 | Dividend Accrual to Income | `test_dividend_transaction_posts_income_and_dividend_record` | `portfolio/test_investment_accounting.py` | P0 |
| AC17.6.3 | GET /portfolio/holdings with as_of_date filter returns 200. | `test_get_holdings_with_date_filter` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.4 | GET /portfolio/holdings with include_disposed=true returns 200. | `test_get_holdings_include_disposed` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.5 | GET /portfolio/performance without period returns metrics. | `test_get_performance_without_period` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.6 | GET /portfolio/performance with period params returns metrics. | `test_get_performance_with_period` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.7 | GET /portfolio/allocation/sector on empty portfolio returns []. | `test_get_sector_allocation_empty` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.8 | GET /portfolio/allocation/sector with data returns breakdown. | `test_get_sector_allocation_with_data` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.9 | GET /portfolio/allocation/geography on empty portfolio returns []. | `test_get_geography_allocation_empty` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.10 | GET /portfolio/allocation/geography with data returns breakdown. | `test_get_geography_allocation_with_data` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.11 | GET /portfolio/allocation/asset-class on empty portfolio returns []. | `test_get_asset_class_allocation_empty` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.12 | GET /portfolio/allocation/asset-class with data returns breakdown. | `test_get_asset_class_allocation_with_data` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.13 | POST /portfolio/prices/update with single asset returns success. | `test_update_prices_single` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.14 | POST /portfolio/prices/update with batch returns success. | `test_update_prices_batch` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.15 | POST /portfolio/prices/update with invalid payload returns 422. | `test_update_prices_invalid_payload` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.16 | All portfolio endpoints require authentication. | `test_portfolio_endpoints_require_auth` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.17 | GET /portfolio/allocation/sector with as_of_date returns 200. | `test_allocation_with_as_of_date` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.18 | GET /portfolio/performance returns string-formatted metrics. | `test_performance_metrics_response_format` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.19 | InsufficientDataError on empty portfolio -> xirr/mwr default to 0. | `test_get_performance_insufficient_data` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.20 | PerformanceError (non-InsufficientData) on XIRR -> 422. | `test_get_performance_xirr_calculation_error` | `portfolio/test_portfolio_router.py` | P1 |
| AC17.6.21 | PerformanceError (non-InsufficientData) on MWR -> 422. | `test_get_performance_mwr_calculation_error` | `portfolio/test_portfolio_router.py` | P1 |

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
| `data_freshness` | Market-data source, latest price date, stale flag, `stale_holdings` per-holding stale list, and manual override basis |
| `source_links` | Source document, brokerage import, price source, and ledger/report traceability anchors |
| `notes` | Human-readable methods and limitations for cost basis, market prices, and return metrics |

When no holding snapshot exists on or before the requested `as_of_date`, the
report schedule may use active current holdings only if the same asset has a
manual market-data override dated after `as_of_date`. This is report-preparation
evidence for EPIC-005 packaging, not a mutation or relaxation of historical
portfolio queries, and the response must disclose the override through notes,
freshness metadata, and source links.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.10.1 | Investment performance schedule API exposes report-ready metrics and rows | `test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule`; `test_AC17_10_1_report_schedule_uses_manual_override_after_period_end`; `test_personal_financial_report_package_post_merge_journey`; `test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract` | `apps/backend/tests/portfolio/test_portfolio_router.py`; `tests/e2e/test_personal_financial_report_package.py`; `tests/tooling/test_investment_performance_report_contract.py` | P0 |
| AC17.10.2 | Investment performance schedule API exposes data freshness, source links, and notes for report traceability | `test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule`; `test_AC17_10_1_report_schedule_uses_manual_override_after_period_end`; `test_personal_financial_report_package_post_merge_journey`; `test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract` | `apps/backend/tests/portfolio/test_portfolio_router.py`; `tests/e2e/test_personal_financial_report_package.py`; `tests/tooling/test_investment_performance_report_contract.py` | P0 |
| AC17.10.3 | Investment performance schedule source links preserve brokerage statement, price source, ledger, transaction source, and report-section anchors | `test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P0 |
| AC17.10.4 | Investment performance schedule data freshness marks the schedule stale when any holding lacks current as-of-date price evidence | `test_AC17_10_4_report_schedule_marks_stale_when_any_holding_price_is_stale` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P0 |
| AC17.10.5 | Investment performance XIRR solver does not convert monetary Decimal cash flows to float | `test_AC17_10_5_xirr_solver_does_not_float_monetary_cashflows` | `apps/backend/tests/portfolio/test_performance_service.py` | P0 |
| AC17.10.6 | Investment performance schedule converts mixed-currency cost basis, market value, realized P&L, and dividend income into presentation currency before aggregation | `test_AC17_10_6_investment_performance_schedule_converts_mixed_currency_amounts` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P0 |

### AC17.11: Portfolio Financial Logic Audit Fixes

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.11.1 | Portfolio XIRR and MWR use investment transactions only, excluding unrelated bank atomic transactions | `test_AC17_11_1_xirr_excludes_unrelated_bank_transactions()` | `portfolio/test_financial_logic_audit.py` | P0 |
| AC17.11.2 | Portfolio summary YTD realized P&L and dividend income are converted to presentation currency before aggregation | `test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency()` | `portfolio/test_financial_logic_audit.py` | P0 |
| AC17.11.3 | Portfolio TWR excludes unrelated bank atomic transactions from period cash-flow adjustment | `test_AC17_11_3_twr_excludes_unrelated_bank_transactions()` | `portfolio/test_financial_logic_audit.py` | P0 |
| AC17.11.4 | Non-structured source document payloads produce no audit links | `test_AC17_11_4_source_document_links_ignore_non_structured_payloads()` | `portfolio/test_financial_logic_audit.py` | P0 |

### AC17.12: Portfolio Audit Fixture Expansion

This block owns the deterministic portfolio fixture contract used by the
personal financial-report package proof. Local real PDF/CSV inputs may be used
to learn statement structure, but committed fixtures must be synthetic,
redacted, and Decimal-safe.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.12.1 | Portfolio audit fixture contract covers multi-broker, multi-currency expected positions and a report period that contains every activity row for Moomoo statement, Moomoo margin history, and Futu statement sources | `test_AC17_12_1_portfolio_fixture_contract_covers_multi_broker_multi_currency_inputs` | `tests/tooling/test_portfolio_audit_fixture_contract.py` | P0 |
| AC17.12.2 | Portfolio audit fixture contract pins sanitized trade, dividend, fee, and valuation activity rows, derives expected totals from fixture rows and positions, and covers parser support for Moomoo margin history rows | `test_AC17_12_2_portfolio_fixture_pins_activity_rows_without_raw_documents`, `test_AC17_12_2_parse_moomoo_margin_history_rows_as_equity_position_snapshot` | `tests/tooling/test_portfolio_audit_fixture_contract.py`, `portfolio/test_brokerage_position_parsing.py` | P0 |
| AC17.12.3 | Personal report package fixture consumes expanded portfolio expected outputs instead of keeping one-position brokerage constants inline | `test_AC17_12_3_personal_package_references_expanded_portfolio_fixture_contract` | `tests/tooling/test_portfolio_audit_fixture_contract.py` | P0 |

### AC17.13: Portfolio Fact Boundary for Framework Reporting

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.13.1 | Portfolio management owns holdings, lots, dividends, fees, prices, freshness, and source links as framework policy inputs, but does not own final US/HK report presentation decisions | `test_AC17_13_1_portfolio_supplies_facts_not_framework_conclusions` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC17.14: Unified Portfolio Allocation Surface

This started as the first frontend slice for #914 and now uses the report-owned
net-worth allocation schedule for the allocation surface. The investment
performance schedule remains the source for period return, unrealized
market-value gain/loss, and price freshness.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.14.1 | Portfolio page renders a unified allocation panel without claiming a portfolio-value tie-out when report and holdings currencies differ | `AC17.14.1 labels allocation and portfolio currencies instead of claiming a portfolio tie-out` | `apps/frontend/src/__tests__/portfolioPage.test.tsx` | P1 |
| AC17.14.2 | Reports expose a net-worth allocation schedule grouped by asset class, liquidity class, and source currency, with signed rows that reconcile to net worth and retain source-line drill-through metadata | `test_AC17_14_2_net_worth_allocation_groups_balance_sheet_sources`, `test_AC17_14_2_net_worth_allocation_endpoint_returns_contract` | `apps/backend/tests/reporting/test_reporting_net_worth_components.py`, `apps/backend/tests/reporting/test_reports_router.py` | P1 |
| AC17.14.3 | Portfolio page consumes the report-owned net-worth allocation schedule, showing asset class, liquidity, source currency, net-worth share, source labels, and restricted-inclusion filtering | `AC17.14.3 renders net-worth allocation from the report schedule`, `AC17.14.3 shows the net-worth allocation loading state`, `AC17.14.3 shows the net-worth allocation error state`, `AC17.14.3 shows the empty net-worth allocation state`, `AC17.14.3 renders invalid net-worth allocation percentages as unavailable`, `AC17.14.3 renders missing net-worth allocation percentages as unavailable`, `AC17.14.3 refetches net-worth allocation when restricted holdings are excluded` | `apps/frontend/src/__tests__/portfolioPage.test.tsx` | P1 |
| AC17.14.4 | The asset-dashboard performance surface leads with unrealized market-value gain/loss, a simple return on cost valued at the schedule as-of date, and a price-freshness flag; TWR/IRR/MWR are not presented as the asset-dashboard answer and stay on the reporting side as clearly-labelled analytical measures | `AC17.14.4 leads with unrealized gain/loss, return on cost, and price freshness`, `AC17.14.4 does not present TWR/IRR/MWR as the asset-dashboard answer`, `AC17.14.4 flags stale prices`, `AC17.14.4 shows N/A return when cost basis is zero` | `apps/frontend/src/__tests__/performanceCard.test.tsx`, `apps/frontend/src/__tests__/investmentPerformanceSchedule.test.tsx` | P1 |

### AC17.15: Non-Ticker Identifier Guard

Brokerage fund positions (e.g. money-market funds) store the full fund name as
`asset_identifier`. That free text was sent to Yahoo Finance as a ticker, 404ing
on every lookup. The guard skips guaranteed-404 Yahoo requests for non-ticker
identifiers (these positions are valued from their existing AtomicPosition
snapshot). The unpriced-drop skip is intentionally kept at `debug` to honor the
high-volume audit-noise contract (AC10.8.4); surfacing dropped positions to the
user (e.g. a report blocker) is tracked as follow-up. Issue #1035.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.15.1 | `_looks_like_ticker` accepts real tickers/FX pairs and rejects fund-name free text | `test_looks_like_ticker_accepts_real_tickers_rejects_free_text` | `apps/backend/tests/market_data/test_provider_parsers.py` | P1 |
| AC17.15.2 | A non-ticker identifier short-circuits the Yahoo stock fetch with no HTTP call | `test_yahoo_stock_fetch_short_circuits_for_non_ticker` | `apps/backend/tests/market_data/test_provider_parsers.py` | P1 |

### AC17.30: List Endpoint Pagination

The portfolio list endpoints (`/holdings`, `/{ticker}/dividends`,
`/{ticker}/realized`, and the three `/allocation/*` surfaces) returned unbounded
`list[...]` payloads with no `limit`/`offset` bounds, the lone gap versus the
statement/journal/account/reconciliation modules (issue #1007). Bounded
`limit`/`offset` query params now apply a sane default cap
(`limit` defaults to 100, `ge=1, le=500`; `offset` `ge=0`, matching the accounts
module). FastAPI rejects out-of-range values with 422. The bare-array response
shape is preserved so existing frontend consumers keep working without coordinated
changes; wrapping these responses in `{items, total}` is deferred to a follow-up
that also migrates the frontend consumers.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.30.1 | GET /portfolio/holdings caps results at the requested limit when paginating | `test_AC17_30_1_holdings_default_cap_applied` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P1 |
| AC17.30.2 | GET /portfolio/holdings honors limit and offset to page through holdings | `test_AC17_30_2_holdings_limit_offset_honored` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P1 |
| AC17.30.3 | GET /portfolio/holdings rejects out-of-range limit/offset with 422 | `test_AC17_30_3_holdings_rejects_out_of_range_pagination` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P1 |
| AC17.30.4 | GET /portfolio/{ticker}/dividends honors limit/offset and rejects out-of-range | `test_AC17_30_4_dividends_limit_offset_honored` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P1 |
| AC17.30.5 | GET /portfolio/{ticker}/realized honors limit/offset and rejects out-of-range | `test_AC17_30_5_realized_limit_offset_honored` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P1 |
| AC17.30.6 | GET /portfolio/allocation/* honors limit/offset and rejects out-of-range | `test_AC17_30_6_allocation_limit_offset_honored` | `apps/backend/tests/portfolio/test_portfolio_router.py` | P1 |

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
| Concurrent auto parse import and manual statement import share the same deduped position instead of failing with a duplicate-key 500 | EPIC-017 | AC17.4.8 | `test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| Statement-scoped import creates holdings | EPIC-017 | AC17.4.6 / AC8.13.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| Imported holdings affect balance sheet value | EPIC-005 / EPIC-017 | AC17.5.4 / AC8.13.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| User completes import and navigates to portfolio value | EPIC-017 | AC17.8.1 / AC17.8.2 / AC17.8.4 | `AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation` | `apps/frontend/src/__tests__/brokerageImportCompletionFlow.test.tsx` | Frontend test |

Provider-backed gate details live in
[EPIC-008](EPIC-008.testing-strategy.md#ac813-tier-3-browser-e2e-full-statement-journey) and
[CI/CD SSOT](../ssot/ci-cd.md#deploy-e2e-gates). The README keeps
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

## Current Scope Decisions

The detailed v1/v2 roadmap, deliverable checklist, technical debt table, and
clarification Q&A were removed as hand-maintained status snapshots. The durable
scope decisions are:

| Decision | Current owner |
|---|---|
| Portfolio is self-developed, not outsourced to a portfolio SaaS | `vision.md` decision 1 and this EPIC objective |
| XIRR/TWR/MWR, allocation, dividends, and cost basis are in portfolio scope | AC17.1-AC17.3, AC17.5-AC17.6, AC17.10-AC17.11 |
| Brokerage statements are uploaded and parsed through the statement pipeline | AC17.4, EPIC-003/EPIC-013 extraction SSOT |
| Manual price update remains valid for low-frequency holdings; provider sync is governed separately | AC17.1.6, [market_data.md](../ssot/market_data.md), AC11.10 |
| Report-ready investment schedule is consumed by the personal report package | AC17.10 and EPIC-005 package contract |
| Framework-specific report presentation for portfolio facts is not owned here | [framework-reporting.md](../ssot/framework-reporting.md), EPIC-020, AC17.13 |

Current proof status comes from generated registries, traceability checks, tests,
critical proof matrix rows, and CI artifacts. Open product questions should be
tracked as issues or new ACs, not as pending prose.

## Historical Audit Notes

The April 2026 FE/UI audit snapshot was removed from this EPIC. Current portfolio UI scope is represented by the AC group below and executable frontend tests.

---

## 🆕 UI Gap Audit (April 2026) — Dividends, Cost Basis, Realized P&L Frontend

**Origin**: UI gap audit against [Project Vision](../target.md) decision 1 (100% self-developed portfolio with XIRR/TWR/MWR, dividend tracking, cost basis methods). Backend portfolio APIs are planned but the frontend has no surfaces for dividend history, cost-basis selection, or realized P&L per holding.

### Acceptance Criteria

- [x] **AC17.7.1** Holding detail page `/portfolio/[ticker]` renders three tabs: `Overview`, `Dividends`, `Realized P&L`
- [x] **AC17.7.2** Dividends tab lists historical dividend events `{ex_date, pay_date, amount, currency, reinvested}` from `GET /api/portfolio/{ticker}/dividends`
- [x] **AC17.7.3** Cost-basis method selector (`FIFO` / `LIFO` / `AvgCost`) on holding detail page persists per-holding via `PATCH /api/portfolio/{ticker}` and re-fetches realized P&L
- [x] **AC17.7.4** Realized P&L tab shows lot-level table `{lot_id, acquired_date, sold_date, quantity, basis, proceeds, gain_loss, holding_period}` from `GET /api/portfolio/{ticker}/realized`
- [x] **AC17.7.5** Portfolio summary card on dashboard adds `realized_pnl_ytd` and `dividend_income_ytd` figures from `GET /api/portfolio/summary`
- [x] **AC17.7.6** Frontend test mounts HoldingDetailPage, switches to Dividends tab, and asserts dividend row labels render

**Priority**: P1 — depends on backend portfolio API delivery; surfaces vision-critical metrics.
**Estimated effort**: 5-7 days frontend (3 tabs + cost-basis selector + summary additions); backend dividend/realized endpoints tracked in core EPIC-017 scope.

### AC17.31: Portfolio Typed Responses ([#1008](https://github.com/wangzitian0/finance_report/issues/1008))

Tier 2 of #1000. `POST /portfolio/prices/update` and `PATCH /portfolio/{ticker}`
declare typed Pydantic responses (`PriceUpdateBatchResponse`,
`CostBasisMethodUpdateResponse`) instead of raw `dict`, so the response contract is
visible in OpenAPI and the generated frontend client.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC17.31.1 | `prices/update` returns the typed `{updated_count, results}` shape | `test_AC17_31_1_prices_update_returns_typed_batch_response` | `api/test_typed_contract_sweep.py` | P2 |
| AC17.31.2 | `PATCH {ticker}` for an unknown holding returns a structured 404 | `test_AC17_31_2_patch_unknown_holding_returns_404` | `api/test_typed_contract_sweep.py` | P2 |
