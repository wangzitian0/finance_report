# EPIC-011: Asset Lifecycle Management

**Status**: 🟡 In Progress (P0 Complete)  
**Vision Anchor**: `decision-3-record-layer`  
**Phase**: 5  
**Duration**: 18 weeks (6 weeks asset features + 12 weeks 4-layer migration)  
**Priority**: P2 (Medium Priority)  
**Dependencies**: EPIC-002 (Double-Entry Core), EPIC-005 (Reporting)

> **Status ownership**: This EPIC owns scope and AC definitions. Current proof
> status comes from generated registries, traceability checks, tests, and CI
> artifacts.

> **Note**: This EPIC includes both asset lifecycle features (6 weeks) and foundational 4-layer architecture migration (12 weeks). The 4-layer migration affects EPIC-003, EPIC-004, EPIC-005 and should be prioritized first.

---

## 📋 Executive Summary

**Goal**: Implement comprehensive **non-cash asset tracking** with automated valuation updates, depreciation schedules, and balance sheet integration.

**Scope**:
- **Securities** (Moomoo, Ping An Securities, ESOP) → Market value tracking
- **Real Estate** (Property - Mortgage) → Appraisal-based valuation
- **Depreciable Assets** (Electronics, Equipment) → Straight-line/accelerated depreciation
- **Intangible Assets** (ESOP vesting schedule)

**Out of Scope**:
- Trading execution (buy/sell orders)
- Portfolio optimization or robo-advisory
- Crypto wallet integration
- Collectibles (art, wine, etc.)

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `annualized-income-long-term`

---

## 🎯 Business Value

### Current Pain Points
1. **Securities hidden in bank balances** → No visibility into stock/bond holdings
2. **Property value stale** → Manual updates, no integration with appraisals
3. **Depreciation ignored** → Balance sheet overstates asset value
4. **ESOP vesting unclear** → No tracking of unvested options

### Success Metrics
- **Accuracy**: ≤ 1% variance between reported and real asset values
- **Automation**: ≥ 90% of securities valuations auto-updated
- **Coverage**: All asset classes represented in balance sheet
- **Timeliness**: Real estate valuations updated quarterly, securities daily

---

## Source Of Truth And Scope Management

This EPIC owns the asset-lifecycle scope and AC definitions. Durable design
facts are managed by the SSOT/code surfaces below instead of being copied here:

| Fact | Owner |
|---|---|
| Four-layer raw/atomic/logic/report architecture | [assets.md](../ssot/assets.md), [schema.md](../ssot/schema.md), models, migrations |
| Upload, extraction, and atomic record flow | [extraction.md](../ssot/extraction.md), `apps/backend/src/services/extraction.py` |
| Reconciliation and reporting integration | [reconciliation.md](../ssot/reconciliation.md), [reporting.md](../ssot/reporting.md) |
| Market data sync, freshness, and provider fallback | [market_data.md](../ssot/market_data.md), `apps/backend/src/services/market_data.py` |
| AC-to-test proof and current counts | `python tools/analyze_test_ac_coverage.py --no-write --stdout`, CI traceability artifact |

Historical migration options, copied table schemas, and implementation-phase
plans were removed from this EPIC because they duplicated SSOT/model ownership.
The retained information is recoverable from the linked SSOT files, executable
code, tests, issues, and git history.

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using AC11.x.y numbering.
> **Coverage**: See `apps/backend/tests/assets/`

### AC11.1: Asset Service - Reconciliation Logic

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.1.1 | Reconcile creates new position | `test_reconcile_creates_position()` | `assets/test_asset_service.py` | P0 |
| AC11.1.2 | Reconcile updates existing position quantity | `test_reconcile_updates_position()` | `assets/test_asset_service.py` | P0 |
| AC11.1.3 | Reconcile disposes position when quantity is 0 | `test_reconcile_disposes_position()` | `assets/test_asset_service.py` | P0 |
| AC11.1.4 | Cost basis is set from market_value | `test_reconcile_cost_basis_uses_market_value()` | `assets/test_asset_service.py` | P0 |
| AC11.1.5 | Reconcile multiple different assets | `test_reconcile_multiple_assets()` | `assets/test_asset_service.py` | P0 |
| AC11.1.6 | Same asset at different brokers creates separate positions | `test_reconcile_multiple_brokers_same_asset()` | `assets/test_asset_service.py` | P0 |
| AC11.1.7 | Null broker name handled correctly | `test_reconcile_with_null_broker()` | `assets/test_asset_service.py` | P1 |
| AC11.1.8 | Disposed position can be reactivated | `test_reconcile_reactivates_disposed_position()` | `assets/test_asset_service.py` | P0 |
| AC11.1.9 | Get positions returns empty list when no positions exist | `test_get_positions_empty()` | `assets/test_asset_service.py` | P0 |
| AC11.1.10 | Reconcile with no snapshots does nothing | `test_reconcile_no_snapshots()` | `assets/test_asset_service.py` | P0 |
| AC11.1.11 | Negative quantities (short positions) handled correctly | `test_reconcile_negative_quantity_short_position()` | `assets/test_asset_service.py` | P1 |
| AC11.1.12 | Updated and disposed counts are mutually exclusive | `test_reconcile_result_counts_are_mutually_exclusive()` | `assets/test_asset_service.py` | P0 |

### AC11.2: Asset Router - List Operations

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.2.1 | GET /assets/positions returns empty list when no positions | `test_list_positions_empty()` | `assets/test_assets_router.py` | P0 |
| AC11.2.2 | GET /assets/positions returns positions with data | `test_list_positions_with_data()` | `assets/test_assets_router.py` | P0 |
| AC11.2.3 | GET /assets/positions filters by status correctly | `test_list_positions_filter_by_status()` | `assets/test_assets_router.py` | P0 |

### AC11.3: Asset Router - Single Position Operations

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.3.1 | GET /assets/positions/{id} returns position details | `test_get_position_success()` | `assets/test_assets_router.py` | P0 |
| AC11.3.2 | GET /assets/positions/{id} returns 404 for non-existent position | `test_get_position_not_found()` | `assets/test_assets_router.py` | P0 |
| AC11.3.3 | GET /assets/positions/{id} returns 404 for other user's position | `test_get_position_wrong_user()` | `assets/test_assets_router.py` | P0 |

### AC11.4: Asset Router - Reconciliation Endpoint

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.4.1 | POST /assets/reconcile creates positions from snapshots | `test_reconcile_positions_success()` | `assets/test_assets_router.py` | P0 |
| AC11.4.2 | POST /assets/reconcile with no snapshots returns 0 counts | `test_reconcile_positions_empty()` | `assets/test_assets_router.py` | P0 |

### AC11.5: Asset Router - Authentication

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.5.1 | GET /assets/positions requires authentication | `test_list_positions_requires_auth()` | `assets/test_assets_router.py` | P0 |
| AC11.5.2 | GET /assets/positions/{id} requires authentication | `test_get_position_requires_auth()` | `assets/test_assets_router.py` | P0 |
| AC11.5.3 | POST /assets/reconcile requires authentication | `test_reconcile_requires_auth()` | `assets/test_assets_router.py` | P0 |

### AC11.6: Asset Router - Depreciation Endpoint

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.6.1 | GET /assets/positions/{id}/depreciation returns depreciation schedule | `test_get_position_depreciation_success()` | `assets/test_assets_router.py` | P0 |
| AC11.6.2 | GET /assets/positions/{id}/depreciation returns 400 for non-existent position | `test_get_position_depreciation_not_found()` | `assets/test_assets_router.py` | P0 |
| AC11.6.3 | GET /assets/positions/{id}/depreciation returns 400 for disposed position | `test_get_position_depreciation_disposed_position()` | `assets/test_assets_router.py` | P0 |
| AC11.6.4 | GET /assets/positions/{id}/depreciation returns 422 for invalid params | `test_get_position_depreciation_invalid_params()` | `assets/test_assets_router.py` | P1 |

### AC11.7: Security - User Isolation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.7.1 | Verify position queries are isolated by user_id | `test_get_position_user_isolation()` | `assets/test_assets_router.py` | P0 |

### AC11.10: Daily Market Data Sync

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.10.1 | Stock price sync fetches daily prices for active holdings and stores idempotent rows | `test_sync_stock_prices_inserts_missing_daily_rows_and_is_idempotent()` | `market_data/test_sync.py` | P0 |
| AC11.10.2 | FX sync fetches explicit or observed pairs incrementally, with USD/base as the default non-empty pair | `test_sync_fx_rates_starts_after_last_stored_date()` | `market_data/test_sync.py` | P0 |
| AC11.10.3 | Missing trading days are recorded as misses without failing the whole sync | `test_sync_stock_prices_records_missing_trading_days()` | `market_data/test_sync.py` | P0 |
| AC11.10.4 | Primary and secondary providers are cross-validated and disagreements are not silently persisted | `test_stock_provider_disagreement_is_reported_without_persisting()` | `market_data/test_sync.py` | P0 |
| AC11.10.5 | Market data sync endpoints expose FX and stock sync status for scheduler/E2E callers | `test_market_data_sync_endpoints_return_counts()` | `market_data/test_sync_router.py` | P0 |
| AC11.10.6 | Portfolio valuation prefers synced stock prices over stale brokerage snapshots | `test_portfolio_uses_synced_stock_price_before_atomic_snapshot()` | `market_data/test_sync.py` | P0 |
| AC11.10.7 | E2E gates cover provider-backed FX sync and stock-price portfolio valuation paths | `test_market_data_provider_sync_feeds_fx_and_stock_price_paths()` | `tests/e2e/test_market_data_price_paths.py` | P0 |
| AC11.10.8 | Long historical market data sync uses bounded range provider requests instead of per-day provider calls | `test_sync_stock_prices_fetches_decade_range_once()` | `market_data/test_sync.py` | P0 |
| AC11.10.9 | Report reads check market data freshness and trigger at most one immediate refresh when the last successful sync is older than 24 hours | `test_market_data_freshness_sync_runs_once_after_24h()` | `market_data/test_sync.py` | P0 |
| AC11.10.10 | Backend scheduler runs daily market data sync at the nightly Asia/Singapore close-refresh window | `test_next_market_data_sync_at_uses_nightly_sgt_schedule()` | `market_data/test_scheduler.py` | P0 |
| AC11.10.11 | Staging E2E covers report-time market data refresh from an authenticated ordinary-user path without manual sync | `test_market_data_provider_sync_feeds_fx_and_stock_price_paths()` | `tests/e2e/test_market_data_price_paths.py` | P0 |

### AC11.11: 4-Layer Migration — Stage 1 Dual-Write Activation

Stage 1 of the 4-layer cutover turns dual-write ON by default: every parsed
statement populates Layer 1/2 (`UploadedDocument` + `AtomicTransaction`)
alongside legacy Layer 0, with an env opt-out preserved for rollback.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.11.1 | Parsing populates Layer 1/2 by default, without any feature-flag override | `test_dual_write_enabled_by_default()` | `extraction/test_dual_write_layer2.py` | P0 |
| AC11.11.2 | `ENABLE_4_LAYER_WRITE=false` preserves the legacy Layer-0-only opt-out for rollback | `test_dual_write_can_be_disabled_via_flag()` | `extraction/test_dual_write_layer2.py` | P0 |

### AC11.12: 4-Layer Migration — Stage 2a Layer 0→2 Backfill

Stage 2a backfills historical Layer 0 statements (those uploaded before Stage 1
dual-write) into Layer 1/2, so the Layer-2 read path has complete coverage
before `ENABLE_4_LAYER_READ` is activated. Idempotent and re-runnable via
`tools/backfill_layer2.py`.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.12.1 | Historical Layer 0 statements are projected into Layer 1 documents and Layer 2 atomic transactions | `test_backfill_creates_layer1_and_layer2_from_legacy_statement()` | `extraction/test_backfill_layer2.py` | P0 |
| AC11.12.2 | Re-running the backfill upserts by dedup hash instead of duplicating rows | `test_backfill_is_idempotent()` | `extraction/test_backfill_layer2.py` | P0 |
| AC11.12.3 | A user-scoped backfill ignores other users' statements | `test_backfill_scopes_to_requested_user()` | `extraction/test_backfill_layer2.py` | P0 |

## Implementation Pattern Ownership

Do not copy reusable code patterns, router examples, migration guardrails, or
test inventories into this EPIC. Those facts are owned by the implementation and
its guardrails:

| Pattern | Owner |
|---|---|
| Service/router/session conventions | Existing backend modules and `apps/backend/README.md` |
| Monetary precision and enum naming | [red-lines.md](../agents/red-lines.md), schema guardrail tests |
| Frontend API access and component conventions | [frontend-patterns.md](../ssot/frontend-patterns.md), `apps/frontend/src/lib/api.ts` |
| Test ownership and execution stage | [test-execution-matrix.yaml](../ssot/test-execution-matrix.yaml), AC traceability artifact |

End-to-end user workflows are represented as ACs plus executable tests. Keep new
workflow detail in tests, critical proof matrix rows, or SSOT rationale instead
of adding another hand-maintained checklist here.

## ✅ Acceptance Criteria

This section retains only EPIC-owned acceptance criteria that are not already
represented in the detailed AC tables above or below. Current proof status is
generated from the registry and tests, not from checkboxes in this file.

- **AC11.9.1 Manual Valuation Snapshot CRUD**: `POST/GET/PATCH/DELETE /api/assets/valuation-snapshots` records property value, mortgage/loan balance, CPF/long-term savings, tax payable/refund, insurance cash value, ESOP/RSU/options, source, notes, reminder cadence, and audit timestamps.
- **AC11.9.2 Net Worth Components**: Latest manual snapshots aggregate into asset/liability deltas with `Decimal` arithmetic.
- **AC11.9.3 Liquidity Separation**: Restricted and illiquid components are tagged separately and can be excluded from liquid net worth views.
- **AC11.9.4 Frontend Entry**: `/assets` exposes a manual valuation entry form and recent snapshot list using the shared API client.

Broader future scope such as depreciation schedules, ESOP grant management,
automated journal posting, charting, and tax-lot functionality remains product
scope only until it receives explicit ACs and executable proof. Technical risks,
provider choices, and accounting decisions are documented in the SSOT files
listed below.

## 📚 Related Documentation

- [accounting.md](../ssot/accounting.md) — Double-entry rules
- [schema.md](../ssot/schema.md) — Database models
- [reporting.md](../ssot/reporting.md) — Financial reports
- [market_data.md](../ssot/market_data.md) — Market data sources
- [assets.md](../ssot/assets.md) — Asset lifecycle rationale and proof references

---

## Archive And Future-Work Ownership

Removed archive snapshots are retained through [issue #548](https://github.com/wangzitian0/finance_report/issues/548)
and git history. Current remaining scope is not tracked by prose-only future-work
lists; it must be represented by one of these owners:

| Scope | Owner |
|---|---|
| Asset lifecycle rationale and data-model links | [assets.md](../ssot/assets.md), [schema.md](../ssot/schema.md) |
| Annualized income / restricted holdings UI gap | AC11.8 below |
| Personal report package annualized-income schedule | AC11.11 below and EPIC-005 package contract |
| Layer 3 classification service | AC11.12 below and extraction service tests |

## 🆕 UI Gap Audit (April 2026) — Annualized Income & ESOP Surfacing

**Origin**: UI gap audit against [Project Vision](../target.md) (annualized salary, ESOP/RSU vesting, restricted-asset visibility). Backend asset lifecycle is complete but the dashboard does not surface annualized income or ESOP/restricted holdings; user has no view of "earnings power vs. liquid wealth".

### Acceptance Criteria

- [x] **AC11.8.1** API endpoint `GET /api/income/annualized` returns `{annualized_salary, annualized_bonus, annualized_dividend, annualized_total, currency, as_of}` derived from last 12 months of Income-type journal entries
- [x] **AC11.8.2** Dashboard "Annualized Income" card renders the four annualized figures with the currency code and `as_of` date subtitle
- [x] **AC11.8.3** API endpoint `GET /api/assets/restricted` returns ESOP/RSU/locked holdings with `{ticker, quantity, vesting_schedule, unlock_date, fair_value}`
- [x] **AC11.8.4** Dashboard "Restricted Holdings" card lists restricted holdings separated from liquid net worth, with vesting timeline tooltip
- [x] **AC11.8.5** Net worth calculation toggle on dashboard (`include_restricted=true|false`) re-fetches and updates total, defaulting to `false` (vision: liquid wealth is primary)
- [x] **AC11.8.6** Frontend test mounts AnnualizedIncomeCard and asserts the four metric labels render
- [x] **AC11.8.7** API endpoint `GET /api/income/annualized` converts mixed-currency annualized income totals into the dashboard reporting currency before aggregation

**Priority**: P1 (high) — closes the largest "vision parity" gap after net worth time series.
**Estimated effort**: 4-6 days backend (income aggregation + restricted-flag schema check) + 3-4 days frontend.

### Personal Report Package Dependency

[#566](https://github.com/wangzitian0/finance_report/issues/566) owns the
annualized income and long-term compensation proof path needed by the personal
financial-report package tracked in
[#563](https://github.com/wangzitian0/finance_report/issues/563). This EPIC
must supply report-ready schedules for salary, dividends, ESOP/RSU, restricted
holdings, vesting/unlock dates, valuation basis, and liquid-versus-restricted
net worth treatment.

For #521 closure, this EPIC sequence is:

1. Consume the package section contract from `#570`.
2. Finalize annualized income and long-term compensation schedule data
   (`#566`, done via `GET /api/reports/package/annualized-income-schedule`).
3. Prove the annualized income and long-term compensation schedule in the
   implemented `#565` post-merge package proof.
4. Land supporting explanation assets for the broader package:
   - report notes (`#571`)
   - traceability appendix (`#572`)
5. Provide deterministic fixture inputs for the remaining package completeness
   proof (`#573`).

`#570`, `#571`, and `#572` are shared package prerequisites with EPIC-005;
`#566` supplies the report-ready schedule contract and the `#565` package E2E
now proves `annualized-income-long-term` in
`docs/ssot/critical-proof-matrix.yaml`. `#573` remains responsible for the
representative fixture expansion needed before the overall
`personal-financial-report-package` macro can move from `partial` to `covered`.

### Acceptance Criteria — Report Package Annualized Income Schedule

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.11.1 | `GET /api/reports/package/annualized-income-schedule` returns annualized salary, bonus, dividend, total income, currency, as-of date, and trailing-period boundaries for the personal report package | `test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment` | `reporting/test_annualized_income_schedule.py` | P0 |
| AC11.11.2 | The schedule includes ESOP/RSU/stock-option restricted holdings with valuation basis, vesting/unlock metadata, fair value, and explicit liquid-versus-restricted net worth treatment | `test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment` | `reporting/test_annualized_income_schedule.py` | P0 |
| AC11.11.3 | Annualized income and restricted fair-value package totals are Decimal-safe and converted to the schedule reporting currency | `test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals` | `reporting/test_annualized_income_schedule.py` | P0 |

### Acceptance Criteria — Layer 3 Classification Service

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.12.1 | Re-applying the same rule version to the same atomic transaction is idempotent and returns the existing classification without inserting duplicates | `test_apply_rules_is_idempotent_for_existing_transaction_rule_version` | `extraction/test_classification_service.py` | P0 |
| AC11.12.2 | Classification priority is deterministic across rule type and descending rule version | `test_classification_priority_keyword_over_regex_over_ml`, `test_same_type_rules_prefer_newer_version` | `extraction/test_classification_service.py` | P0 |
