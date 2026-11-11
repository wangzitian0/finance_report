"""Machine-checkable PackageContract for ``portfolio``."""

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
@$be/portfolio/test_investment_accounting.py|P0
posting-inputs.1|Investment posting accepts TradeOrder, TradeAccounts.|test_AC_portfolio_posting_inputs_1_value_objects_bound_the_write_signature|P1
1.1|Post_buy posts a balanced ledger entry, creates the opening InvestmentLot.|test_buy_transaction_creates_balanced_journal_entry_and_lot
2.1|Post_sell consumes InvestmentLots by the configured FIFO cost-basis method and never sells more than the remaining quantity.|test_sell_transaction_uses_fifo_and_records_realized_gain
2.2|Post_sell supports average-cost disposal and persists the AVGCOST method on the realized transaction and remaining position.|test_sell_transaction_uses_average_cost_for_realized_pnl
3.1|A sell updates ManagedPosition quantity and disposal status.|test_sell_transaction_uses_lifo_loss_and_disposes_position
4.1|Post_dividend posts cash plus dividend income and persists a DividendIncome record for the position.|test_dividend_transaction_posts_income_and_dividend_record
4.2|Post_dividend splits withholding tax into separate cash and tax expense legs.|test_dividend_transaction_posts_withholding_tax|P1
1.2|Investment accounting rejects invalid buy, sell.|test_investment_accounting_rejects_invalid_transactions
1.3|Investment accounting helper lookups reject missing positions and inactive or wrong-type accounts with clean domain errors.|test_investment_accounting_rejects_invalid_account_and_position_helpers|P1
2427.1|Balance-sheet trade/loan disposition resolves code-keyed default counter accounts.|test_AC_portfolio_2427_1_balance_sheet_disposition_honors_trade_account_and_skips_duplicate_trade|P1
@$be/assets/test_asset_service.py|P0
reconcile.1|Reconcile creates a new ManagedPosition from an AtomicPosition snapshot.|test_reconcile_creates_position
reconcile.2|Reconcile updates an existing position's quantity from the latest snapshot.|test_reconcile_updates_position
reconcile.3|Reconcile disposes a position.|test_reconcile_disposes_position
reconcile.4|Reconcile sets cost basis from the snapshot's market_value.|test_reconcile_cost_basis_uses_market_value
reconcile.5|Reconcile handles multiple different assets in one run.|test_reconcile_multiple_assets
reconcile.6|The same asset at different brokers reconciles into separate positions.|test_reconcile_multiple_brokers_same_asset
reconcile.7|A null/missing broker name falls back to 'Unknown Broker'.|test_reconcile_with_null_broker|P1
reconcile.8|A disposed position reactivates to ACTIVE.|test_reconcile_reactivates_disposed_position
reconcile.9|Listing positions returns an empty list.|test_get_positions_empty
reconcile.10|Reconcile with no atomic snapshots is a no-op.|test_reconcile_no_snapshots
reconcile.11|Negative quantities reconcile correctly, not as an error.|test_reconcile_negative_quantity_short_position|P1
reconcile.12|A single reconcile run's updated and disposed position counts are mutually exclusive.|test_reconcile_result_counts_are_mutually_exclusive
@$be/assets/test_assets_router.py|P0
router.1|GET /assets/positions returns an empty list.|test_list_positions_empty
router.2|GET /assets/positions returns the user's positions with data.|test_list_positions_with_data
router.3|GET /assets/positions filters correctly by status.|test_list_positions_filter_by_status
router.4|GET /assets/positions/{id} returns the position's details.|test_get_position_success
router.5|GET /assets/positions/{id} returns 404 for a non-existent position.|test_get_position_not_found
router.6|GET /assets/positions/{id} returns 404 for another user's position.|test_get_position_wrong_user
router.7|POST /assets/reconcile creates positions from the latest atomic snapshots.|test_reconcile_positions_success
router.8|POST /assets/reconcile with no snapshots returns zero created/updated/disposed counts.|test_reconcile_positions_empty
router.9|GET /assets/positions requires authentication.|test_list_positions_requires_auth
router.10|GET /assets/positions/{id} requires authentication.|test_get_position_requires_auth
router.11|POST /assets/reconcile requires authentication.|test_reconcile_requires_auth
router.12|Position queries are isolated by user_id.|test_get_position_user_isolation
depreciation.1|GET /assets/positions/{id}/depreciation returns the depreciation schedule.|test_get_position_depreciation_success
depreciation.2|GET /assets/positions/{id}/depreciation returns 400 for a non-existent position.|test_get_position_depreciation_not_found
depreciation.3|GET /assets/positions/{id}/depreciation returns 400 for a disposed position.|test_get_position_depreciation_disposed_position
depreciation.4|GET /assets/positions/{id}/depreciation returns 422 for invalid method/parameters.|test_get_position_depreciation_invalid_params|P1
@$be/portfolio/test_portfolio_service.py|P1
holdings.1|Get_holdings returns the holdings summary for active positions.|test_get_holdings_happy_path|P0
holdings.2|Unrealized P&L is calculated from cost basis and current market value.|test_unrealized_pnl_happy_path|P0
holdings.3|The portfolio summary happy path returns correct counts and totals.|test_portfolio_summary_happy
holdings.4|The portfolio summary includes both active and disposed positions.|test_portfolio_summary_with_disposed
holdings.5|A zero total cost yields net_pnl_percent = 0.|test_portfolio_summary_zero_cost
performance.4|A zero cost basis yields realized_pnl_percent = 0.|test_realized_pnl_zero_cost
performance.5|A disposed position in a non-base currency triggers FX conversion for realized P&L.|test_realized_pnl_fx_conversion
performance.6|Unrealized P&L on an empty portfolio raises PortfolioNotFoundError.|test_unrealized_pnl_no_positions
performance.7|A zero cost basis yields unrealized_pnl_percent = 0 in per-position details.|test_unrealized_pnl_zero_cost
performance.8|Unrealized P&L converts non-base-currency positions via FX.|test_unrealized_pnl_fx_conversion
valuation.2|A zero-quantity position returns its market_value directly.|test_get_latest_price_zero_quantity
valuation.3|Missing price data raises AssetNotFoundError.|test_get_latest_price_no_data
valuation.4|_get_latest_atomic returns the most recent snapshot.|test_get_latest_atomic_returns_latest
valuation.5|_get_latest_atomic returns None when no snapshots exist.|test_get_latest_atomic_none
as-of.1|Historical holdings quantity and market value come from the latest AtomicPosition snapshot at or.|test_get_holdings_explicit_as_of_uses_historical_atomic_snapshot|P0
provenance.1|A holding whose latest snapshot is backed by a source document is labeled imported.|test_get_holdings_provenance_imported_with_source_document
provenance.2|Portfolio holdings and explicit as-of holdings expose the normalized provenance enum.|test_AC22_13_1_explicit_as_of_holdings_preserve_snapshot_provenance
@$be/portfolio/test_portfolio_router.py|P1
holdings.6|GET /portfolio/holdings responds in the repo-standard items+total wrapper with a warnings list.|test_AC_portfolio_holdings_6_unreconciled_snapshot_disclosed_in_warnings
api.1|GET /portfolio/holdings with an as_of_date filter returns 200.|test_get_holdings_with_date_filter
api.2|GET /portfolio/holdings with include_disposed=true returns 200.|test_get_holdings_include_disposed
api.3|GET /portfolio/performance without a period returns metrics.|test_get_performance_without_period
api.4|GET /portfolio/performance with period params returns metrics.|test_get_performance_with_period
api.5|GET /portfolio/allocation/sector on an empty portfolio returns [].|test_get_sector_allocation_empty
api.6|GET /portfolio/allocation/sector with data returns the breakdown.|test_get_sector_allocation_with_data
api.7|GET /portfolio/allocation/geography on an empty portfolio returns [].|test_get_geography_allocation_empty
api.8|GET /portfolio/allocation/geography with data returns the breakdown.|test_get_geography_allocation_with_data
api.9|GET /portfolio/allocation/asset-class on an empty portfolio returns [].|test_get_asset_class_allocation_empty
api.10|GET /portfolio/allocation/asset-class with data returns the breakdown.|test_get_asset_class_allocation_with_data
api.11|POST /portfolio/prices/update with a single asset returns success.|test_update_prices_single
api.12|POST /portfolio/prices/update with a batch returns success.|test_update_prices_batch
api.13|POST /portfolio/prices/update with an invalid payload returns 422.|test_update_prices_invalid_payload
api.14|All portfolio endpoints require authentication.|test_portfolio_endpoints_require_auth
api.15|GET /portfolio/allocation/sector with as_of_date returns 200.|test_allocation_with_as_of_date
api.16|GET /portfolio/performance returns string-formatted metrics.|test_performance_metrics_response_format
api.17|GET /portfolio/performance returns null metrics and populates unavailable_reasons.|test_get_performance_insufficient_data
api.18|A non-InsufficientData PerformanceError on XIRR returns 422.|test_get_performance_xirr_calculation_error
api.19|A non-InsufficientData PerformanceError on MWR returns 422.|test_get_performance_mwr_calculation_error
2673.1|POST /portfolio/{ticker}/dividends routes.|test_AC_portfolio_2673_1_create_holding_dividend_posts_balanced_journal_entry
as-of.2|The holdings API returns date-bounded snapshot quantities for explicit as_of_date requests.|test_get_holdings_explicit_date_uses_historical_snapshot_quantity|P0
report-schedule.1|The investment performance schedule API exposes report-ready metrics and per-holding/allocation rows.|test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule|P0
report-schedule.3|Schedule source links preserve brokerage statement, price source, ledger, transaction source.|test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule|P0
report-schedule.4|Schedule data freshness marks the schedule stale.|test_AC17_10_4_report_schedule_marks_stale_when_any_holding_price_is_stale|P0
report-schedule.6|The schedule converts mixed-currency cost basis, market value, realized P&L.|test_AC17_10_6_investment_performance_schedule_converts_mixed_currency_amounts|P0
pagination.1|GET /portfolio/holdings caps results at the default limit.|test_AC17_30_1_holdings_default_cap_applied
pagination.2|GET /portfolio/holdings honors limit and offset to page.|test_AC17_30_2_holdings_limit_offset_honored
pagination.3|GET /portfolio/holdings rejects out-of-range limit/offset with 422.|test_AC17_30_3_holdings_rejects_out_of_range_pagination
pagination.4|GET /portfolio/{ticker}/dividends honors limit/offset and rejects out-of-range values.|test_AC17_30_4_dividends_limit_offset_honored
pagination.5|GET /portfolio/{ticker}/realized honors limit/offset and rejects out-of-range values.|test_AC17_30_5_realized_limit_offset_honored
pagination.6|GET /portfolio/allocation/* honors limit/offset and rejects out-of-range values.|test_AC17_30_6_allocation_limit_offset_honored
schedule-fallback.1|The mixed-currency investment schedule fallback converts holding cost basis into the schedule currency.|test_AC19_8_8_investment_schedule_fallback_holding_cost_basis_converts_currency|P0
@$be/portfolio/test_performance_service.py|P1
performance.1|XIRR over realistic data is accurate.|test_xirr_with_realistic_data|P0
performance.2|Time-weighted return is computed correctly for a period.|test_time_weighted_return_with_period|P0
performance.3|Money-weighted return is computed from dated cash flows.|test_money_weighted_return_with_data
allocation.4|MWR raises InsufficientDataError on an empty portfolio.|test_money_weighted_return_insufficient_data
allocation.5|XIRR respects the as_of_date parameter.|test_xirr_with_as_of_date
allocation.6|TWR returns zero for a same-day period.|test_time_weighted_return_same_day
allocation.7|Performance metrics handle cash-only portfolios without positions.|test_performance_metrics_with_zero_positions
allocation.8|XIRR handles extreme convergence edge cases.|test_xirr_convergence_edge_case
allocation.9|_xirr_bisection raises ValueError when no root exists.|test_xirr_bisection_no_root_raises
allocation.10|_xirr_bisection returns a Decimal estimate.|test_xirr_bisection_max_iter_returns
allocation.11|_xirr_newton falls back to bisection on non-convergence.|test_xirr_newton_fallthrough_to_bisection
allocation.12|XIRRCalculationError is raised when Newton and bisection both fail.|test_xirr_calculation_error_raised
report-schedule.5|The XIRR solver never converts monetary Decimal cash flows to float.|test_AC17_10_5_xirr_solver_does_not_float_monetary_cashflows|P0
metrics.1|XIRR matches the single-year Excel XIRR reference case within 0.01%.|test_AC5_6_1_xirr_matches_single_year_excel_case|P0
metrics.2|Annualized time-weighted return matches the snapshot period reference.|test_AC5_6_2_time_weighted_return_matches_snapshot_period|P0
metrics.3|Dividend yield is trailing annual dividends over current value.|test_AC5_6_3_dividend_yield_uses_trailing_dividends_over_current_value|P0
metrics.4|Money-weighted return matches XIRR for a single cash flow.|test_AC5_6_6_money_weighted_return_matches_xirr_for_single_cashflow
metrics.5|A position's contribution to XIRR/TWR/dividend-yield portfolio value as of a historical date is decided by whether it was held on that date, not by ManagedPosition.status which reflects today -- a position disposed.|test_AC5_6_3_dividend_yield_counts_position_disposed_after_as_of_date|P0:property
@$be/portfolio/test_allocation_service.py|P1
allocation.1|Sector allocation breaks holdings down by sector.|test_sector_allocation_with_positions
allocation.2|Geography allocation breaks holdings down by geography.|test_geography_allocation_with_positions
allocation.3|Asset-class allocation breaks holdings down by asset class.|test_asset_class_allocation_with_positions
@$be/portfolio/test_brokerage_position_parsing.py|P1
valuation.1|Unrealized P&L flows into the balance sheet with EXACT values.|test_statement_import_flows_to_holdings_and_balance_sheet|P0:exact
brokerage-import.1|Moomoo brokerage statement parsing extracts subscription positions.|test_parse_moomoo_fixture_subscription_positions|P0
brokerage-import.2|Futu brokerage statement parsing aggregates positions.|test_parse_futu_fixture_aggregate_position
brokerage-import.3|Interactive Brokers positions import idempotently and reconcile on re-import.|test_import_interactive_brokers_positions_idempotently_reconciles
brokerage-import.4|Broker auto-detection identifies Moomoo, Futu.|test_detect_broker_moomoo_futu_and_interactive_brokers
brokerage-import.5|The brokerage import endpoint flows a statement import into holdings and the balance sheet.|test_brokerage_import_endpoint
brokerage-import.6|Concurrent auto and manual brokerage import survives.|test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import|P0
brokerage-import.7|Importing brokerage positions links the statement to the broker ASSET account it reconciles into.|test_AC17_4_14_brokerage_import_links_statement_to_broker_account
brokerage-import.8|An auto-created broker account adopts the holding's currency.|test_AC17_33_3_broker_account_uses_snapshot_currency_not_hardcoded_usd
brokerage-import.9|A short position imports as a signed position.|test_AC17_34_1_brokerage_import_persists_short_positions_with_negative_market_value
brokerage-import.10|`POST /portfolio/brokerage/import` validates the payload at the wire boundary.|test_AC_brokerage_import_10_payload_rejects_json_floats|P0
@$be/portfolio/test_financial_logic_audit.py|P0
logic-audit.1|XIRR and MWR use investment transactions only, excluding unrelated bank atomic transactions.|test_AC17_11_1_xirr_excludes_unrelated_bank_transactions
logic-audit.2|Summary YTD realized P&L and dividend income convert to the presentation currency.|test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency
logic-audit.3|TWR excludes unrelated bank atomic transactions from the period cash-flow adjustment.|test_AC17_11_3_twr_excludes_unrelated_bank_transactions
logic-audit.4|Non-structured source document payloads produce no audit links.|test_AC17_11_4_source_document_links_ignore_non_structured_payloads
@$t/test_portfolio_audit_fixture_contract.py|P0
fixtures.1|The portfolio audit fixture contract covers multi-broker, multi-currency expected positions and a report period containing every activity row.|test_AC17_12_1_portfolio_fixture_contract_covers_multi_broker_multi_currency_inputs
fixtures.2|The fixture contract pins sanitized trade, dividend, fee.|test_AC17_12_2_portfolio_fixture_pins_activity_rows_without_raw_documents
fixtures.3|The personal report package fixture consumes the expanded portfolio expected outputs.|test_AC17_12_3_personal_package_references_expanded_portfolio_fixture_contract
@$be/api/test_typed_contract_sweep.py|P2
typed-responses.1|POST /portfolio/prices/update returns the typed {updated_count, results} shape.|test_AC17_31_1_prices_update_returns_typed_batch_response
typed-responses.2|PATCH /portfolio/{ticker} for an unknown holding returns a structured 404.|test_AC17_31_2_patch_unknown_holding_returns_404
@$be/portfolio/test_brokerage_import_error_contract.py|P1
brokerage-import.11|A parsed positions source that states no as-of date does not import.|test_AC_portfolio_brokerage_import_11_dateless_positions_csv_returns_422_reason
brokerage-import.12|The import returns 422 with `error_id` `brokerage_position_out_of_range` and a reason that names the position and the field, not 500, for these cases.|test_AC_portfolio_brokerage_import_12_unstorable_positions_return_422_reason
brokerage-import.13|BrokeragePositionImportService rejects a source_document_id containing a NUL byte or exceeding 255 characters with 422 brokerage_position_out_of_range.|test_AC_portfolio_brokerage_import_13_invalid_source_document_id_and_legacy_currency_return_422
@$fe/__tests__/portfolioPage.test.tsx|P1
fe-assets.1|Portfolio page renders loading and error retry states.|AC16.15.4 renders loading and error retry states while fetching holdings|P2
fe-assets.2|Portfolio page renders grouped positions and status filters on successful fetch.|AC16.15.5 renders grouped positions and supports status filters|P2
fe-assets2.1|The portfolio page labels retirement and benefit asset entry options as assets, with insurance represented only by cash value.|AC11.20.3 labels retirement and benefit assets in net-worth allocation
fe-assets2.16|Portfolio page exposes an as-of date selector and passes it to `/api/portfolio/holdings`.|AC17.9.3 passes selected as-of date to holdings API|P0
fe-assets2.17|Portfolio page renders a unified allocation panel.|AC17.14.1 labels allocation and portfolio currencies instead of claiming a portfolio tie-out
fe-assets2.18|Portfolio page consumes the report-owned net-worth allocation schedule, showing asset class, liquidity, source currency, net-worth share, source labels.|AC17.14.3 renders net-worth allocation from the report schedule
fe-net-worth-sources.1|A ledger account source of a Portfolio allocation row opens the account lineage drawer.|#2645 opens the lineage drawer from a ledger source and links no source to an API path
fe-net-worth-sources.2|With restricted holdings excluded, Portfolio labels the figure Liquid net worth and lists each excluded asset class with its amount.|#2645 labels the liquid net worth and names each excluded class when restricted holdings are excluded
fe-assets2.24|Portfolio summary card on dashboard adds `realized_pnl_ytd` and `dividend_income_ytd` figures from `GET /api/portfolio/summary`.|AC17.7.5 renders realized P&L YTD and dividend income YTD from portfolio summary|P2
fe-panels.1|The `/portfolio` page opens one drawer from its URL.|AC-portfolio.fe-panels.1 opens one drawer from the ticker or panel query parameter and closes it to /portfolio
@$fe/__tests__/brokerageImportCompletionFlow.test.tsx|P0
fe-assets.3|Brokerage import completion and portfolio value navigation.|AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation|P2
fe-assets2.11|Import to Portfolio button visible for parsed/approved statements.|AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation
fe-assets2.12|Import result banner with stats and portfolio link shown on success.|AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation
fe-assets2.14|Portfolio page shows total portfolio value prominently after import.|AC16.15.6 AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation
@$fe/__tests__/guidedEvidenceForm.test.tsx|P2
fe-ia-portfolio.2|Manual valuation capture uses a controlled source enum.|AC11.9.4 AC22.10.2 AC11.9.7 valid submit posts a Decimal-safe payload through the typed client|P1
fe-assets2.2|The evidence drawer of `/portfolio` exposes a manual valuation entry form using the shared API client.|AC11.9.4 AC22.10.2 AC11.9.7 valid submit posts a Decimal-safe payload through the typed client
fe-assets2.3|([#706]): the shared guided evidence form for the three source classes blocks submission and shows a readiness blocker.|AC11.9.6 validateEvidenceForm flags missing basis and as-of date
fe-assets2.4|([#706]): a valid guided evidence submission persists.|AC11.9.4 AC22.10.2 AC11.9.7 valid submit posts a Decimal-safe payload through the typed client
fe-assets2.5|([#706]): the guided evidence flow surfaces a clear "Manual-trusted" disclosure badge for manually entered evidence.|AC11.9.8 form shows a manual-trusted badge
fe-assets2.6|([#706]): the guided evidence form renders an accessible single-column mobile layout.|AC11.9.9 renders accessible single-column form on a mobile viewport
@$fe/__tests__/personalReportPackagePage.test.tsx|P2
fe-assets2.7|The Full package tab of `/reports` renders the annualized income figures with the currency code.|AC5.11.2 renders annualized income schedule values and restricted treatment
fe-assets2.8|The Full package tab of `/reports` lists the restricted holdings with their fair value apart from the liquid annualized income.|AC5.11.2 renders annualized income schedule values and restricted treatment
fe-assets2.10|A frontend test mounts the annualized income schedule of the Full package tab and asserts the salary, bonus, dividend and total figures.|AC5.11.2 renders annualized income schedule values and restricted treatment
@$fe/__tests__/statementDetailPage.coverage.test.tsx|P0
fe-assets2.13|Import failure shows actionable error without sensitive data.|AC17.8.3 shows actionable import error banner without exposing sensitive data
fe-assets2.15|Import button hidden for non-parsed/approved statements.|AC17.8.5 does not show Import to Portfolio for non-parsed statements
@$fe/__tests__/holdingDetailPage.test.tsx|P2
fe-assets2.20|The holding drawer of `/portfolio` renders three tabs.|AC17.7.1 renders Overview, Dividends, and Realized P&L tabs
fe-assets2.21|Dividends tab lists historical dividend events `{ex_date, pay_date, amount, currency, reinvested}` from `GET /api/portfolio/{ticker}/dividends`.|AC17.7.2/AC17.7.6 switches to Dividends tab and renders dividend row labels|-|decision-1-portfolio-self-developed
fe-assets2.22|Cost-basis method selector on holding detail page persists per-holding.|AC17.7.3 persists cost-basis method and refetches realized P&L
fe-assets2.23|Realized P&L tab shows lot-level table `{lot_id, acquired_date, sold_date, quantity, basis, proceeds, gain_loss, holding_period}` from `GET /api/portfolio/{ticker}/realized`.|AC17.7.4 renders lot-level realized P&L table
@-|P1
report-schedule.2|The schedule API exposes data freshness, source links.|$t/test_investment_performance_report_contract.py::test_AC17_10_1_AC17_10_2_investment_performance_schedule_api_contract|P0
fact-boundary.1|Portfolio owns holdings, lots, dividends, fees.|$t/test_framework_reporting_epic_contract.py::test_AC17_13_1_portfolio_supplies_facts_not_framework_conclusions|P0
fe-ia-portfolio.1|The holdings table renders the "Imported" provenance badge only for holdings with concrete document evidence.|$fe/__tests__/holdingsTable.test.tsx::AC22.10.1 AC22.13.2 shows provenance badges only when provenance is known
fe-ia-portfolio.3|Desktop and mobile Playwright smoke covers portfolio provenance badges only for imported holdings, with unproven holdings unlabeled and no document horizontal overflow.|apps/frontend/playwright/portfolio-provenance.spec.ts::${scenario.name} labels only imported holdings with provenance
fe-ia-portfolio.4|Portfolio and report surfaces render a shared Imported / Manual / Derived provenance badge.|$fe/__tests__/provenanceBadge.test.tsx::AC22.13.2 renders normalized Imported, Manual, and Derived badges
fe-assets2.9|The restricted-holdings scope of the Home dimension bar re-fetches the balance sheets and updates net worth, with the default `true`.|$fe/__tests__/dashboardPage.test.tsx::AC11.8.5 defaults to the full net worth and labels each excluded class when restricted holdings are excluded|P2
fe-assets2.19|The asset-dashboard performance surface leads with unrealized market-value gain/loss, a simple return on cost valued at the schedule as-of date.|$fe/__tests__/performanceCard.test.tsx::AC17.14.4 leads with unrealized gain/loss, return on cost, and price freshness
""",
    ),
)
