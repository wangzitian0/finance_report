# EPIC-011: Asset Lifecycle Management

**Status**: 🟡 In Progress (P0 Complete)  
**Vision Anchor**: `decision-3-record-layer`  
**Phase**: 5  
**Duration**: 18 weeks (6 weeks asset features + 12 weeks 4-layer migration)  
**Priority**: P2 (Medium Priority)  
**Dependencies**: EPIC-002 (Double-Entry Core), EPIC-005 (Reporting)

> **Usable milestone**: ⏸️ deferred (post-Usable). P0 asset tracking is done; depreciation / ESOP / valuation-history depth is owned here but **not** required for the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1) (upload a year of real data on prod).

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

### AC11.13: 4-Layer Migration — Stage 1 Dual-Write Activation

Stage 1 of the 4-layer cutover turns dual-write ON by default: every parsed
statement populates Layer 1/2 (`UploadedDocument` + `AtomicTransaction`)
alongside legacy Layer 0, with an env opt-out preserved for rollback.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.13.1 | Parsing populates Layer 1/2 by default, without any feature-flag override | `test_dual_write_enabled_by_default()` | `extraction/test_dual_write_layer2.py` | P0 |

### AC11.14: 4-Layer Migration — Stage 2a Layer 0→2 Backfill (RETIRED in Stage 3)

> **Retired.** The Stage-2a backfill (`tools/backfill_layer2.py`) and its tests
> were transitional scaffolding to populate Layer 1/2 from legacy Layer-0
> statements before the read cutover. Stage 3 removes the `bank_statements`
> tables entirely and the ingestion pipeline writes Layer 1/2 + the
> `StatementSummary` conform directly, so there is no Layer-0 source to backfill
> from. The backfill acceptance criteria are obsolete and have been removed.

### AC11.15: 4-Layer Migration — StatementSummary Conform (custody account)

The durable `StatementSummary` conform binds an uploaded statement document to its
custody account (DIM) and carries the confirmed statement envelope (period,
balances, review state). It is the DWD-native home for the account context
reconciliation transfer detection needs. As of Stage 3 the ingestion pipeline
writes the conform directly (the legacy `BankStatement`→`StatementSummary` sync
was removed with the `bank_statements` table).

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.15.3 | Custody account resolves from a Layer-2 atomic transaction via the conform (DWD-native) | `test_resolve_custody_account_from_atomic_txn()` | `extraction/test_statement_summary_conform.py` | P0 |
| AC11.15.4 | The resolver returns None when the source statement has no confirmed custody account | `test_resolve_returns_none_without_account()` | `extraction/test_statement_summary_conform.py` | P0 |
| AC11.15.5 | The resolver normalizes a `{"documents": [...]}` source-documents wrapper | `test_resolve_handles_dict_wrapper_source_documents()` | `extraction/test_statement_summary_conform.py` | P0 |
| AC11.15.6 | The resolver skips junk entries, non-bank-statement sources, and invalid UUIDs | `test_resolve_ignores_invalid_and_non_bank_sources()` | `extraction/test_statement_summary_conform.py` | P0 |
| AC11.15.7 | A non-list/non-dict source_documents value resolves to None | `test_resolve_returns_none_for_non_list_source_documents()` | `extraction/test_statement_summary_conform.py` | P0 |
| AC11.15.8 | The first source document (in order) with a confirmed account wins | `test_resolve_preserves_source_document_order()` | `extraction/test_statement_summary_conform.py` | P0 |
| AC11.15.9 | A known source document with no confirmed custody account resolves to None | `test_resolve_returns_none_when_no_source_has_account()` | `extraction/test_statement_summary_conform.py` | P0 |

### AC11.16: 4-Layer Migration — Balance-aware Layer 2 dedup

The Layer 2 `dedup_hash` includes the statement running balance (`balance_after`)
so two real, otherwise-identical transactions (same date/amount/direction/
description, no reference) stay distinct — their running balances differ — while
genuine duplicate extractions (same running balance) still collapse. This keeps
many-to-one reconciliation correct on the Layer-2 read path.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.16.1 | Distinct running balances hash differently; identical/absent balances collapse | `test_running_balance_distinguishes_identical_transactions()` | `extraction/test_deduplication.py` | P0 |
| AC11.16.2 | Many-to-one matching works on Layer 2 when running balances keep batch txns distinct | `test_execute_matching_many_to_one_batch()` | `reconciliation/test_reconciliation_matching_unit.py` | P0 |

### AC11.17: 4-Layer Migration — PR-B DWD read cutover

PR-B activates `ENABLE_4_LAYER_READ` by default: reconciliation reads Layer 2
(`atomic_transactions`) and transfer detection resolves the custody account from
the `StatementSummary` conform (DWD) instead of `bank_statements.account_id`
(ODS). The legacy Layer-0 read path remains available via the flag until Stage 3.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.17.1 | Transfer OUT/IN detection resolves custody account from DWD and creates the Processing entry under the Layer-2 read path | `test_transfer_out_creates_match()`, `test_transfer_in_creates_match()` | `reconciliation/test_reconciliation_matching_unit.py` | P0 |
| AC11.17.2 | Mixed transfer + normal transactions both reconcile under the Layer-2 read path | `test_mixed_transactions_both_phases_execute()` | `reconciliation/test_transfer_integration.py` | P0 |

### AC11.18: 4-Layer Migration — Financial Fact Schema Invariants

Financial source facts and derived snapshots reject invalid financial states at
the database layer before reporting, readiness checks, or export paths need to
guess around them. The invariant set covers positive financial facts, statement
envelope completeness, deterministic asset and market-data uniqueness, and
latest-report snapshot guards. Short positions remain valid: negative position
quantity is allowed, while market value and cost facts stay non-negative.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.18.1 | Positive source fact constraints reject zero or negative atomic and manual valuation amounts while allowing valid short-position quantities | `test_AC11_18_1_positive_source_fact_constraints()` | `infra/test_financial_fact_schema_invariants.py` | P0 |
| AC11.18.2 | Approved statement summaries require account, currency, period, and balance fields, and statement periods cannot be inverted | `test_AC11_18_2_statement_summary_approved_completeness_and_period_order()` | `infra/test_financial_fact_schema_invariants.py` | P0 |
| AC11.18.3 | Managed positions, investment lots, and investment facts enforce deterministic uniqueness and non-negative quantity/cost relationships | `test_AC11_18_3_portfolio_fact_constraints_and_managed_position_uniqueness()` | `infra/test_financial_fact_schema_invariants.py` | P0 |
| AC11.18.4 | Latest report snapshots cannot conflict for the same logical report scope and report date ranges cannot be inverted | `test_AC11_18_4_report_snapshot_latest_scope_and_date_constraints()` | `infra/test_financial_fact_schema_invariants.py` | P0 |
| AC11.18.5 | Market-data facts enforce positive rates/prices and stock prices are unique by symbol, currency, provider source, and date | `test_AC11_18_5_market_data_constraints_and_stock_price_uniqueness()` | `infra/test_financial_fact_schema_invariants.py` | P0 |
| AC11.18.6 | The constraint migration declares preflight checks and migration-risk classification for existing data compatibility | `test_AC11_18_6_migration_preflights_and_risk_contract_are_declared()` | `infra/test_financial_fact_schema_invariants.py` | P0 |

### AC11.19: Append-Only Manual Valuation Facts (Axiom A)

Manual valuation snapshots are user-supplied source facts. Per vision Axiom A a
recorded fact is never edited in place: correcting a valuation for an existing
`(component_type, source, as_of_date)` appends a new version and supersedes the
prior one, so the correction history stays retrievable and one version maps to
exactly one value. Uniqueness applies to the current head only (a partial unique
index over `superseded_by_id IS NULL`); read paths and net-worth aggregation use
the current head so a correction never double-counts. (In-place value editing via
the PATCH endpoint is the documented next slice; see #918.)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.19.1 | Correcting a manual valuation appends a new version and preserves the prior fact unedited as a retrievable superseded version | `test_AC11_19_1_manual_valuation_correction_appends_version_and_preserves_history()` | `assets/test_manual_valuation_snapshots.py` | P1 |
| AC11.19.2 | Heads-only reads use the current version so a corrected valuation is never double-counted in net worth or listings | `test_AC11_19_2_corrected_valuation_is_not_double_counted_in_net_worth()` | `assets/test_manual_valuation_snapshots.py` | P1 |

### AC11.20: Retirement and Benefit Assets

Retirement accounts, personal social-security balances, CPF-style balances,
long-term benefit accounts, and insurance cash value are assets. They are not
insurance coverage or future benefits; only the attributable/account value is
recorded. By default they are restricted assets, included in full net-worth
views and grouped separately from liquid cash, public equity, property, and
restricted compensation.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.20.1 | Retirement accounts, social-security personal balances, legacy CPF, and insurance cash value default to restricted assets and contribute to full balance-sheet assets | `test_AC11_20_1_retirement_and_benefit_assets_are_restricted_assets_in_balance_sheet()` | `reporting/test_reporting_net_worth_components.py` | P1 |
| AC11.20.2 | Net-worth allocation groups retirement accounts, social-security personal balances, legacy CPF, and insurance cash value under the retirement-and-benefit asset class | `test_AC11_20_2_net_worth_allocation_groups_retirement_and_benefit_assets()` | `reporting/test_reporting_net_worth_components.py` | P1 |
| AC11.20.3 | The assets page labels retirement and benefit asset entry options as assets, with insurance represented only by cash value | `test_AC11_20_3_assets_page_surfaces_retirement_and_benefit_asset_labels()` | `apps/frontend/src/__tests__/assetsPage.test.tsx` | P1 |

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
- **AC11.9.5 Structured Valuation Basis & Evidence Gate** ([#706](https://github.com/wangzitian0/finance_report/issues/706)): a manual valuation captures an optional structured `valuation_basis` (market appraisal, broker/bank/government/insurer statement, employer grant document, self-estimate); a current manual valuation that carries no structured basis (and no legacy notes) surfaces a `missing_valuation_basis` readiness blocker — replacing the free-text-notes proxy — so an unsubstantiated value cannot silently feed trusted totals. Monetary values remain `Decimal`-safe.
- **AC11.9.6 Guided Evidence Form — required-field validation** ([#706](https://github.com/wangzitian0/finance_report/issues/706)): the shared guided evidence form for the three source classes (`esop_rsu_plan`, `property_statement`, `liability_statement`) blocks submission and shows a readiness blocker when the required `valuation_basis` or `as_of_date` is missing, never calling the API; value is carried as a `Decimal`-safe string with no float math. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.6 *`.
- **AC11.9.7 Guided Evidence Form — typed manual-valuation persistence** ([#706](https://github.com/wangzitian0/finance_report/issues/706)): a valid guided evidence submission persists through the existing `POST /api/assets/valuation-snapshots` endpoint via the typed `lib/api.ts` client (never raw `fetch`), mapping the chosen source class to its `component_type`, `valuation_basis`, source label, anchor, and notes, with the monetary `value` sent as a string. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.7 *`.
- **AC11.9.8 Manual-trusted disclosure label** ([#706](https://github.com/wangzitian0/finance_report/issues/706)): the guided evidence flow surfaces a clear "Manual-trusted" disclosure badge for manually entered evidence so users and the traceability appendix can see the source-trust state of a value. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.8 *`.
- **AC11.9.9 Guided Evidence Form — mobile layout** ([#706](https://github.com/wangzitian0/finance_report/issues/706)): the guided evidence form renders an accessible single-column mobile layout (and the recent-evidence list) when a mobile viewport is reported by `matchMedia`, and degrades gracefully when `matchMedia` is unavailable. Proven by `apps/frontend/src/__tests__/guidedEvidenceForm.test.tsx::AC11.9.9 *`.
- **AC11.9.10 Traceability appendix surfaces valuation basis** ([#706](https://github.com/wangzitian0/finance_report/issues/706)): the package traceability appendix surfaces each manual valuation snapshot's structured `valuation_basis` (the enum value, or `unspecified` when no basis was captured) in its source-anchor detail so the audit trail records how a manual-trusted value was substantiated. Proven by `test_AC11_9_10_package_traceability_surfaces_manual_valuation_basis` in `apps/backend/tests/api/test_personal_report_package_contract.py`.

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
the derived critical-proof matrix (source `docs/ssot/critical-proof-outcomes.yaml`). `#573` remains responsible for the
representative fixture expansion needed before the overall
`personal-financial-report-package` macro can move from `partial` to `covered`.

### Acceptance Criteria — Report Package Annualized Income Schedule

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.11.1 | `GET /api/reports/package/annualized-income-schedule` returns annualized salary, bonus, dividend, total income, currency, as-of date, and trailing-period boundaries for the personal report package | `test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment` | `reporting/test_annualized_income_schedule.py` | P0 |
| AC11.11.2 | The schedule includes ESOP/RSU/stock-option restricted holdings with valuation basis, vesting/unlock metadata, fair value, and explicit liquid-versus-restricted net worth treatment | `test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment` | `reporting/test_annualized_income_schedule.py` | P0 |
| AC11.11.3 | Annualized income and restricted fair-value package totals are Decimal-safe and converted to the schedule reporting currency | `test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals` | `reporting/test_annualized_income_schedule.py` | P0 |
| AC11.11.4 | Each restricted holding's `valuation_basis` surfaces the snapshot's structured evidence basis enum value (or `unspecified` when none was captured) instead of a hardcoded source-kind literal ([#706](https://github.com/wangzitian0/finance_report/issues/706)) | `test_AC11_11_4_annualized_schedule_surfaces_structured_valuation_basis` | `reporting/test_annualized_income_schedule.py` | P0 |

### Acceptance Criteria — Layer 3 Classification Service

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC11.12.1 | Re-applying the same rule version to the same atomic transaction is idempotent and returns the existing classification without inserting duplicates | `test_apply_rules_is_idempotent_for_existing_transaction_rule_version` | `extraction/test_classification_service.py` | P0 |
| AC11.12.2 | Classification priority is deterministic across rule type and descending rule version | `test_classification_priority_keyword_over_regex_over_ml`, `test_same_type_rules_prefer_newer_version` | `extraction/test_classification_service.py` | P0 |
