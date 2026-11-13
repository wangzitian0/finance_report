"""PackageContract for ``portfolio``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="portfolio",
    status="active",
    tier="CODE-ONLY",
    depends_on="audit extraction ledger observability platform pricing".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/portfolio", "fe": None},
    context=ContextScope(
        purpose="Own investment position accounting.",
        in_scope=[
            "ManagedPosition, investment lots, investment transactions.",
            "Cost-basis selection, holdings, allocation.",
            "Portfolio-owned trade accounting inputs before ledger posting.",
        ],
        out_of_scope=[
            "Source-document/AtomicPosition lifecycle and extraction provenance.",
            "Double-entry journal ownership or price/FX observation and resolution ownership.",
            "Shared value language, telemetry/persistence substrate, report presentation.",
        ],
    ),
    relationships=rels(
        "portfolio",
        """
audit|published-language|Uses audit Money, Quantity, UnitPrice.
extraction|projection|Reads extraction-owned AtomicPosition and managed-position snapshots as brokerage input.
ledger|consumer-port|Submits balanced trade and dividend entries.
observability|published-language|Uses published safe logging language for portfolio calculation diagnostics.
platform|composition|Uses platform ORM persistence mixins.
pricing|published-language|Consumes pricing valuation and FX-resolution language but never fetches, stores, or resolves price observations itself.
""",
    ),
    units=units(
        """
@vo|base/errors.py|PortfolioError PortfolioNotFoundError InvalidDateRangeError AssetNotFoundError InvestmentAccountingError InvestmentAccountingValidationError
@vo|base/types.py|DividendEvent TradeAccounts TradeOrder
ManagedPosition|agg
@ent|-|InvestmentLot InvestmentTransaction DividendIncome
@vo|-|PositionStatus CostBasisMethod InvestmentTransactionType DividendType InvestmentAccountingResult
InvestmentAccountingService|svc|extension/accounting.py
PortfolioRepository|repo
PortfolioService|svc|extension/holdings.py
@svc|extension/allocation.py|get_sector_allocation get_geography_allocation get_asset_class_allocation
@svc|extension/performance.py|calculate_xirr calculate_time_weighted_return calculate_money_weighted_return calculate_dividend_yield
build_investment_performance_report_schedule|svc|extension/performance_report.py
@svc|extension/discovery.py|active_stock_symbols position_currencies
@proj|-|HoldingResponse RealizedPnLResponse UnrealizedPnLResponse PortfolioSummaryResponse
"""
    ),
    interface="""
AssetNotFoundError DepreciationResult DividendIncome DividendEvent DividendType
InsufficientDataError InvalidDateRangeError InvestmentAccountingError
InvestmentAccountingResult InvestmentAccountingService
InvestmentAccountingValidationError InvestmentLot InvestmentTransaction
InvestmentTransactionType PerformanceError PortfolioError PortfolioNotFoundError
PortfolioService PositionService PositionServiceError ReconcileResult TradeAccounts
TradeOrder XIRRCalculationError active_stock_symbols
build_investment_performance_report_schedule calculate_dividend_yield
calculate_money_weighted_return calculate_time_weighted_return calculate_xirr
get_asset_class_allocation get_geography_allocation get_sector_allocation
portfolio_service position_currencies
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_portfolio_package.py
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_AC_portfolio_1_1_only_all_is_the_published_language
converges-by-layer|The package converges into base/ + extension/ + data/.|test_AC_portfolio_1_2_converges_by_layer
base-layer-pure|Base/ never imports the package's own extension/ or data/, the ORM, or any network client.|test_AC_portfolio_1_3_base_layer_is_pure
passes-own-governance-gate|Check_package_contract validates portfolio with no violations.|test_AC_portfolio_1_4_package_contract_gate_passes
"""
    ),
    roadmap=acs(
        "portfolio",
        """
@$be/portfolio/test_investment_accounting.py
posting-inputs.1||test_AC_portfolio_posting_inputs_1_value_objects_bound_the_write_signature|P1
1.1||test_buy_transaction_creates_balanced_journal_entry_and_lot
2.1||test_sell_transaction_uses_fifo_and_records_realized_gain
2.2||test_sell_transaction_uses_average_cost_for_realized_pnl
3.1||test_sell_transaction_uses_lifo_loss_and_disposes_position
4.1||test_dividend_transaction_posts_income_and_dividend_record
4.2||test_dividend_transaction_posts_withholding_tax|P1
1.2||test_investment_accounting_rejects_invalid_transactions
1.3||test_investment_accounting_rejects_invalid_account_and_position_helpers|P1
2427.1||test_AC_portfolio_2427_1_balance_sheet_disposition_honors_trade_account_and_skips_duplicate_trade|P1
@$be/assets/test_asset_service.py
reconcile.1||test_reconcile_creates_position
reconcile.2||test_reconcile_updates_position
reconcile.3||test_reconcile_disposes_position
reconcile.4||test_reconcile_cost_basis_uses_market_value
reconcile.5||test_reconcile_multiple_assets
reconcile.6||test_reconcile_multiple_brokers_same_asset
reconcile.7||test_reconcile_with_null_broker|P1
reconcile.8||test_reconcile_reactivates_disposed_position
reconcile.9||test_get_positions_empty
reconcile.10||test_reconcile_no_snapshots
reconcile.11||test_reconcile_negative_quantity_short_position|P1
reconcile.12||test_reconcile_result_counts_are_mutually_exclusive
@$be/assets/test_assets_router.py
router.1||test_list_positions_empty
router.2||test_list_positions_with_data
router.3||test_list_positions_filter_by_status
router.4||test_get_position_success
router.5||test_get_position_not_found
router.6||test_get_position_wrong_user
router.7||test_reconcile_positions_success
router.8||test_reconcile_positions_empty
router.9||test_list_positions_requires_auth
router.10||test_get_position_requires_auth
router.11||test_reconcile_requires_auth
router.12||test_get_position_user_isolation
depreciation.1||test_get_position_depreciation_success
depreciation.2||test_get_position_depreciation_not_found
depreciation.3||test_get_position_depreciation_disposed_position
depreciation.4||test_get_position_depreciation_invalid_params|P1
@$be/portfolio/test_portfolio_service.py|P1
holdings.1||test_get_holdings_happy_path|P0
holdings.2||test_unrealized_pnl_happy_path|P0
holdings.3||test_portfolio_summary_happy
holdings.4||test_portfolio_summary_with_disposed
holdings.5||test_portfolio_summary_zero_cost
performance.4||test_realized_pnl_zero_cost
performance.5||test_realized_pnl_fx_conversion
performance.6||test_unrealized_pnl_no_positions
performance.7||test_unrealized_pnl_zero_cost
performance.8||test_unrealized_pnl_fx_conversion
valuation.2||test_get_latest_price_zero_quantity
valuation.3||test_get_latest_price_no_data
valuation.4||test_get_latest_atomic_returns_latest
valuation.5||test_get_latest_atomic_none
as-of.1||test_get_holdings_explicit_as_of_uses_historical_atomic_snapshot|P0
provenance.1||test_get_holdings_provenance_imported_with_source_document
provenance.2||test_AC22_13_1_explicit_as_of_holdings_preserve_snapshot_provenance
@$be/portfolio/test_portfolio_router.py|P1
holdings.6||test_AC_portfolio_holdings_6_unreconciled_snapshot_disclosed_in_warnings
api.1||test_get_holdings_with_date_filter
api.2||test_get_holdings_include_disposed
api.5||test_get_sector_allocation_empty
api.6||test_get_sector_allocation_with_data
api.7||test_get_geography_allocation_empty
api.8||test_get_geography_allocation_with_data
api.9||test_get_asset_class_allocation_empty
api.10||test_get_asset_class_allocation_with_data
api.11||test_update_prices_single
api.12||test_update_prices_batch
api.13||test_update_prices_invalid_payload
api.14||test_portfolio_endpoints_require_auth
api.15||test_allocation_with_as_of_date
2673.1||test_AC_portfolio_2673_1_create_holding_dividend_posts_balanced_journal_entry
as-of.2||test_get_holdings_explicit_date_uses_historical_snapshot_quantity|P0
report-schedule.1|The investment performance schedule API exposes report-ready metrics and per-holding/allocation rows.|test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule|P0
report-schedule.3|Schedule source links preserve brokerage statement, price source, ledger, transaction source.|^|P0
report-schedule.4||test_AC17_10_4_report_schedule_marks_stale_when_any_holding_price_is_stale|P0
report-schedule.6||test_AC17_10_6_investment_performance_schedule_converts_mixed_currency_amounts|P0
pagination.1||test_AC17_30_1_holdings_default_cap_applied
pagination.2||test_AC17_30_2_holdings_limit_offset_honored
pagination.3||test_AC17_30_3_holdings_rejects_out_of_range_pagination
pagination.4||test_AC17_30_4_dividends_limit_offset_honored
pagination.5||test_AC17_30_5_realized_limit_offset_honored
pagination.6||test_AC17_30_6_allocation_limit_offset_honored
schedule-fallback.1||test_AC19_8_8_investment_schedule_fallback_holding_cost_basis_converts_currency|P0
@$be/portfolio/test_performance_service.py|P1
performance.1||test_xirr_with_realistic_data|P0
performance.2||test_time_weighted_return_with_period|P0
performance.3||test_money_weighted_return_with_data
allocation.4||test_money_weighted_return_insufficient_data
allocation.5||test_xirr_with_as_of_date
allocation.6||test_time_weighted_return_same_day
allocation.7||test_performance_metrics_with_zero_positions
allocation.8||test_xirr_convergence_edge_case
allocation.9||test_xirr_bisection_no_root_raises
allocation.10||test_xirr_bisection_max_iter_returns
allocation.11||test_xirr_newton_fallthrough_to_bisection
allocation.12||test_xirr_calculation_error_raised
report-schedule.5||test_AC17_10_5_xirr_solver_does_not_float_monetary_cashflows|P0
metrics.1||test_AC5_6_1_xirr_matches_single_year_excel_case|P0
metrics.2||test_AC5_6_2_time_weighted_return_matches_snapshot_period|P0
metrics.3||test_AC5_6_3_dividend_yield_uses_trailing_dividends_over_current_value|P0
metrics.4||test_AC5_6_6_money_weighted_return_matches_xirr_for_single_cashflow
metrics.5||test_AC5_6_3_dividend_yield_counts_position_disposed_after_as_of_date|P0:property
@$be/portfolio/test_allocation_service.py|P1
allocation.1||test_sector_allocation_with_positions
allocation.2||test_geography_allocation_with_positions
allocation.3||test_asset_class_allocation_with_positions
@$be/portfolio/test_brokerage_position_parsing.py|P1
valuation.1||test_statement_import_flows_to_holdings_and_balance_sheet|P0
brokerage-import.1||test_parse_moomoo_fixture_subscription_positions|P0
brokerage-import.2||test_parse_futu_fixture_aggregate_position
brokerage-import.3||test_import_interactive_brokers_positions_idempotently_reconciles
brokerage-import.4||test_detect_broker_moomoo_futu_and_interactive_brokers
brokerage-import.5||test_brokerage_import_endpoint
brokerage-import.6||test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import|P0
brokerage-import.7||test_AC17_4_14_brokerage_import_links_statement_to_broker_account
brokerage-import.8||test_AC17_33_3_broker_account_uses_snapshot_currency_not_hardcoded_usd
brokerage-import.9||test_AC17_34_1_brokerage_import_persists_short_positions_with_negative_market_value
brokerage-import.10||test_AC_brokerage_import_10_payload_rejects_json_floats|P0
@$be/portfolio/test_financial_logic_audit.py
logic-audit.1||test_AC17_11_1_xirr_excludes_unrelated_bank_transactions
logic-audit.2||test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency
logic-audit.3||test_AC17_11_3_twr_excludes_unrelated_bank_transactions
logic-audit.4||test_AC17_11_4_source_document_links_ignore_non_structured_payloads
@$t/test_portfolio_audit_fixture_contract.py
fixtures.1||test_AC17_12_1_portfolio_fixture_contract_covers_multi_broker_multi_currency_inputs
fixtures.2||test_AC17_12_2_portfolio_fixture_pins_activity_rows_without_raw_documents
fixtures.3||test_AC17_12_3_personal_package_references_expanded_portfolio_fixture_contract
@$be/api/test_typed_contract_sweep.py|P2
typed-responses.1||test_AC17_31_1_prices_update_returns_typed_batch_response
typed-responses.2||test_AC17_31_2_patch_unknown_holding_returns_404
@$be/portfolio/test_brokerage_import_error_contract.py|P1
brokerage-import.11||test_AC_portfolio_brokerage_import_11_dateless_positions_csv_returns_422_reason
brokerage-import.12||test_AC_portfolio_brokerage_import_12_unstorable_positions_return_422_reason
brokerage-import.13||test_AC_portfolio_brokerage_import_13_invalid_source_document_id_and_legacy_currency_return_422
@$fe/__tests__/portfolioPage.test.tsx|P1
fe-assets.1||AC16.15.4 renders loading and error retry states while fetching holdings|P2
fe-assets.2||AC16.15.5 renders grouped positions and supports status filters|P2
fe-assets2.1||AC11.20.3 labels retirement and benefit assets in net-worth allocation
fe-assets2.16||AC17.9.3 passes selected as-of date to holdings API|P0
fe-assets2.17||AC17.14.1 labels allocation and portfolio currencies instead of claiming a portfolio tie-out
fe-assets2.18||AC17.14.3 renders net-worth allocation from the report schedule
fe-net-worth-sources.1||#2645 opens the lineage drawer from a ledger source and links no source to an API path
fe-net-worth-sources.2||#2645 labels the liquid net worth and names each excluded class when restricted holdings are excluded
fe-assets2.24||AC17.7.5 renders realized P&L YTD and dividend income YTD from portfolio summary|P2
fe-panels.1||AC-portfolio.fe-panels.1 opens one drawer from the ticker or panel query parameter and closes it to /portfolio
@$fe/__tests__/brokerageImportCompletionFlow.test.tsx
fe-assets.3|Brokerage import completion and portfolio value navigation.|AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation|P2
fe-assets2.11|Import to Portfolio button visible for parsed/approved statements.|^
fe-assets2.12|Import result banner with stats and portfolio link shown on success.|^
fe-assets2.14|Portfolio page shows total portfolio value prominently after import.|^
@$fe/__tests__/guidedEvidenceForm.test.tsx|P2
fe-ia-portfolio.2|Manual valuation capture uses a controlled source enum.|AC11.9.4 AC22.10.2 AC11.9.7 valid submit posts a Decimal-safe payload through the typed client|P1
fe-assets2.2|The evidence drawer of `/portfolio` exposes a manual valuation entry form using the shared API client.|^
fe-assets2.4|([#706]): a valid guided evidence submission persists.|^
fe-assets2.3||AC11.9.6 validateEvidenceForm flags missing basis and as-of date
fe-assets2.5||AC11.9.8 form shows a manual-trusted badge
fe-assets2.6||AC11.9.9 renders accessible single-column form on a mobile viewport
@$fe/__tests__/personalReportPackagePage.test.tsx|P2
fe-assets2.7|The Full package tab of `/reports` renders the annualized income figures with the currency code.|AC5.11.2 renders annualized income schedule values and restricted treatment
fe-assets2.8|The Full package tab of `/reports` lists the restricted holdings with their fair value apart from the liquid annualized income.|^
fe-assets2.10|A frontend test mounts the annualized income schedule of the Full package tab and asserts the salary, bonus, dividend and total figures.|^
@$fe/__tests__/statementDetailPage.coverage.test.tsx
fe-assets2.13||AC17.8.3 shows actionable import error banner without exposing sensitive data
fe-assets2.15||AC17.8.5 does not show Import to Portfolio for non-parsed statements
@$fe/__tests__/holdingDetailPage.test.tsx|P2
fe-assets2.20||AC17.7.1 renders Overview, Dividends, and Realized P&L tabs
fe-assets2.21||AC17.7.2/AC17.7.6 switches to Dividends tab and renders dividend row labels|-|decision-1-portfolio-self-developed
fe-assets2.22||AC17.7.3 persists cost-basis method and refetches realized P&L
fe-assets2.23||AC17.7.4 renders lot-level realized P&L table
@$t/test_investment_performance_report_contract.py
report-schedule.2||test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract
@$t/test_framework_reporting_epic_contract.py
fact-boundary.1||test_AC17_13_1_portfolio_supplies_facts_not_framework_conclusions
@$fe/__tests__/holdingsTable.test.tsx|P1
fe-ia-portfolio.1||AC22.10.1 AC22.13.2 shows provenance badges only when provenance is known
@apps/frontend/playwright/portfolio-provenance.spec.ts|P1
fe-ia-portfolio.3||${scenario.name} labels only imported holdings with provenance
@$fe/__tests__/provenanceBadge.test.tsx|P1
fe-ia-portfolio.4||AC22.13.2 renders normalized Imported, Manual, and Derived badges
@$fe/__tests__/dashboardPage.test.tsx|P2
fe-assets2.9||AC11.8.5 defaults to the full net worth and labels each excluded class when restricted holdings are excluded
@$fe/__tests__/performanceCard.test.tsx|P1
fe-assets2.19||AC17.14.4 leads with unrealized gain/loss, return on cost, and price freshness
""",
    ),
)
