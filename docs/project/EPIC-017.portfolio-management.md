# EPIC-017: Investment Portfolio Management (100% Self-Developed)

> **Status**: 🟡 Planned  
> **Phase**: 5 (Asset Tracking)  
> **Duration**: 6-8 weeks  
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

## ✅ Task Checklist

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

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **XIRR calculation accuracy within 0.01%** | Compare with Excel XIRR (`test_calculate_xirr()`) | 🔴 Critical |
| **Cost basis methods (FIFO/LIFO/AvgCost) accurate** | Unit tests with mock transactions | 🔴 Critical |
| **Brokerage statements auto-parsed (Moomoo, Futu, IB)** | Integration tests with fixture PDFs | Required |
| **Manual price update UI functional** | Manual UI test | Required |
| **Holdings dashboard shows real-time P&L** | Integration test (price update → dashboard refresh) | Required |
| **Dividend income → journal entry → income statement** | End-to-end test | Required |
| **Asset allocation charts accurate** | Unit tests (allocation service) | Required |

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
- [ ] Update `docs/ssot/extraction.md` — Add brokerage statement parsing section
- [ ] Update `README.md` — Add portfolio management feature description

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

## 📅 Timeline

| Phase | Content | Duration | Status |
|------|------|----------|--------|
| **Phase 1** | Data Model & Holdings Tracking | 2 weeks | ⏳ Planned |
| Week 1 | Extend models, create portfolio service | | |
| Week 2 | Performance metrics, allocation service, API endpoints | | |
| **Phase 2** | Brokerage Statement Parsing | 2 weeks | ⏳ Planned |
| Week 3 | Extend extraction service (Moomoo, Futu, IB parsers) | | |
| Week 4 | Processing account integration, tests | | |
| **Phase 3** | Frontend Dashboard & Manual Price UI | 2-3 weeks | ⏳ Planned |
| Week 5 | Portfolio dashboard, holdings table | | |
| Week 6 | Allocation charts, dividend timeline | | |
| Week 7 | Manual price update page, holding detail page | | |
| **Phase 4** | Integration & Performance Optimization | 1-2 weeks | ⏳ Planned |
| Week 8 | Batch optimization, caching, migration | | |

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

*Last updated: February 2026*
