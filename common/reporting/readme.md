# `reporting` — financial report generation over the ledger (domain package)

> Conforming backend implementation: `apps/backend/src/reporting/` (`contract.implementations["be"]`). FX lookup/conversion and manual valuation lines import `pricing` (`common/pricing/readme.md`). See also: `common/ledger/readme.md#decimal-rule`, `common/ledger/readme.md#entry-balance`, `common/reconciliation/readme.md#thresholds`.

## Why

Balance sheet, income statement, cash flow, and net worth read posted/reconciled ledger facts, `pricing` FX/valuations, and `portfolio` holdings through unified read-only views without mutating ledger state.

## Status

`status="active"`, `tier="CODE-ONLY"`. Core modules: `base/{types,l1_registry,report_package_contract}.py` and `extension/{_core,balance_sheet,income_statement,cash_flow,net_worth,lineage,internal_transfer,portfolio_market,framework_policy,framework_report,package_document,report_traceability,report_package,reporting_snapshot,reporting_calc}.py`.

## SSOT: report calculation rules

### Report snapshot determinism

- `report_snapshots` persists frozen report payloads (`is_latest` unique per point-in-time or range key, `start_date <= as_of_date`).
- `PersonalReportPackageDocument` uses `report_type = package`, freezing period, framework, readiness, source-trust summary, policy result, traceability appendix, section payloads, and extraction's `StatementDispositionPolicySnapshot`.
- `POST /api/reports/package/snapshots` persists a snapshot (`trusted` only when readiness is `ready`/`generated`/`stale` with zero blockers; otherwise `draft`). `GET /api/reports/package/snapshots` and `GET /api/reports/package/snapshots/{snapshot_id}` reopen frozen payloads without recalculation.
- Exports (`GET /api/reports/exports` and `GET /api/reports/package/snapshots/{snapshot_id}/exports?format=json|csv`) declare headers through `ExportStreamEnvelope` (`apps/backend/src/schemas/streaming.py`).

### Report types

- **Balance Sheet** (`GET /api/reports/balance-sheet`): point-in-time equation `Total Assets = Total Liabilities + Total Equity + Net Income + Unrealized FX Gain/Loss + Net Worth Adjustment Gain/Loss`.
- **Opening balances**: `POST /api/accounts/opening-balances` creates one balanced posted entry in base currency against `3199 Opening Balance Equity`; all reports read it through the normal ledger query (`common/ledger/readme.md`).
- **Cash flow** (`GET /api/reports/cash-flow`, `GET /api/reports/cash-flow/line-events`): journal-entry event projection over authoritative cash identities (`PackageCashInputs` for packages; bounded compatibility fallback for standalone views). Bridge invariant: `classified + unclassified_cash + fx + opening_stock_adjustment = ending_cash - beginning_cash`. Missing FX fails closed.
- **Net worth time-series** (`GET /api/reports/net-worth/timeseries`): capped at 366 daily/monthly points computed from pre-period balances + daily movements + spot FX (`get_exchange_rate_series`) + manual/portfolio valuations, matching `generate_balance_sheet` on each point date (`AC-reporting.net-worth-timeseries.3`).
- **Net worth allocation** (`GET /api/reports/net-worth/allocation`): signed base-currency breakdown by `asset_class x liquidity_class x source_currency`, reconciling to `net_worth` with drill-through `source_lines`.
- **Investment performance schedule** (`GET /api/portfolio/performance/report-schedule`): query params `period_start`, `period_end`, `as_of_date`, `currency`. Returns Decimal-safe schedule fields: `period_start`, `period_end`, `as_of_date`, `currency`, `xirr`, `time_weighted_return`, `money_weighted_return`, `realized_pnl`, `unrealized_pnl`, `dividend_income`, `dividend_yield`, `holdings`, `allocation`, `data_freshness`, `stale_holdings`, `source_links`, `notes`.
- **Annualized income**: included inside `PersonalReportPackageDocument` over trailing 365 days using trailing average FX rates (`standalone /api/income/annualized` removed in `#3010`).
- **Account lineage** (`GET /api/reports/account-lineage`): tenant-scoped contributing posted/reconciled journal lines for `account_id`.
- **Report line provenance**: `imported | manual | derived | null` plus `allocation_source_type`.

### Personal financial-report package contract

- `GET /api/reports/package` returns bounded `PersonalReportPackagePreview` (keeping every section plus paginated details via `GET /api/reports/package/policy-decisions`, `GET /api/reports/cash-flow/line-events`, `GET /api/reports/package/line-details`, and `GET /api/reports/package/manifest-entries`).
- Required sections: `balance_sheet`, `income_statement`, `cash_flow`, `investment_performance`, `annualized_income_long_term`, `notes`, `traceability_appendix`.
- Required notes: `basis-of-preparation`, `reporting-period-and-currency`, `valuation-basis`, `investment-market-data`, `source-confidence-review`, `restricted-asset-treatment`, plus explicit non-compliance disclosure.
- Package readiness is produced solely by `PackageAssembler` (`assemble` and `evaluate_readiness` share `shared_current_authority` from `#2602`). Workflow and advisor consume `current_package_readiness`; no secondary readiness derivation is allowed.
- Data quality (`GET /api/reports/data-quality`) grades adjacent statement gaps: zero-change (`|delta| <= 0.10`), tiny (`< 0.1%`, absorbed in `3198`), or material (`>= 0.1%`, `UPLOAD_STATEMENT` action items) plus trailing staleness prompts.

### Multi-currency consolidation

- Reports convert foreign amounts to the requested `currency` using **period-end spot FX** (balance sheet) or **average FX** (income statement), surfacing fallback/missing-rate items in `fx_warnings` rather than silently assuming `1:1`.
- Balance sheet combines posted ledger lines, active portfolio market-value adjustments (`market_value - cost_basis`), and manual valuation snapshots.

```python
from src.audit.money import ExchangeRate, Money, convert, to_money


def consolidate_amount(amount: Decimal, currency: str, target: str, as_of: date) -> Decimal:
    if currency == target:
        return to_money(amount)
    rate = get_fx_rate(currency, target, as_of)
    return convert(Money(amount, currency), ExchangeRate(currency, target, rate)).amount
```

<a id="net-worth-scope"></a>
- **Net worth scope (`include_restricted`)**: defaults to `DEFAULT_INCLUDE_RESTRICTED = True` (`DEFAULT_INCLUDE_RESTRICTED = true` in `hooks/useReportFilters.ts`); `PACKAGE_INCLUDE_RESTRICTED = False` in the package view. `include_restricted=false` delegates to `pricing.split_net_worth_scope` and moves excluded assets/linked liabilities into `excluded_holdings` and `net_worth_adjustment_gain_loss`. Restricted-holding FX gaps degrade to warnings on `/reports/data-quality` and package blockers without failing the balance sheet.
- `unrealized_fx_gain_loss` compares foreign-currency balances at report spot FX against historical base cost (excluding legacy `FX_REVALUATION` entries); `net_worth_adjustment_gain_loss` captures non-ledger portfolio/manual deltas explicitly.

### <a id="internal-transfer-net-worth-neutrality"></a>Internal-transfer net-worth neutrality

- Internal own-account transfers cancel to `-fee` (`classify_internal_transfer`). Reporting loads anchored `fx_conversions` rows plus conservative raw-ledger matches (`discover_fx_conversions`), deduplicates unordered entry pairs, and excludes matched legs from income/expense aggregation while attributing holding-period FX moves to unrealized revaluation.

### Report integrity across account and source lifecycles

- Framework policy (`v2.0`) isolates `1199` Processing as **Cash in transit** and assigns rounding residuals deterministically.
- Archived accounts remain included for historical reporting dates; coverage checks (`GET /api/reports/coverage`) bound the default/All cockpit window at `opening_coverage_start` and expose `limiting_accounts` + `latest_statement_end`.
- Home surfaces `HomeActionBanner` (`needs_action` prioritized before unmatched queue; unapproved Stage-1 transactions excluded from Stage-2 purity blockers).
