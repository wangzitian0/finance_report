"""Machine-checkable PackageContract for ``pricing``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="pricing",
    status="active",
    tier="CODE-ONLY",
    depends_on="audit platform observability".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/pricing", "fe": None},
    context=ContextScope(
        purpose="Own price and valuation observations, their bitemporal authority.",
        in_scope=[
            "PriceObservation, PriceableSubject, authority, staleness.",
            "FX rate lookup, valuation observation ingestion.",
            "Pricing-owned PriceObserved events and decision-backed valuation contributions.",
        ],
        out_of_scope=[
            "Document extraction facts and re-parse lifecycle.",
            "Shared money arithmetic and assurance-language ownership.",
            "Portfolio position ownership, report presentation.",
        ],
    ),
    relationships=rels(
        "pricing",
        """
audit|published-language|Uses audit Money, exchange-rate arithmetic.
audit|consumer-port|Consumes audit decision-evidence repository/emitter ports.
platform|consumer-port|Uses platform EventBus/outbox ports to publish pricing events atomically with pricing-owned observations.
platform|composition|Uses platform persistence mixins.
observability|published-language|Uses published safe logging language for provider and resolution diagnostics.
""",
    ),
    units=units(
        """
PriceObservation|agg|base/observation.py
PriceableSubject|vo|base/subject.py
@vo|base/observation.py|ObservationSource Authority
ResolutionPolicy|vo|base/policy.py
PriceObserved|ev|base/events.py
PricingError|vo|base/errors.py
resolve|svc|extension/resolve.py
@svc|extension/manual.py|record_manual_valuation record_override
@svc|extension/fx.py|get_exchange_rate get_exchange_rate_series convert_amount convert_money get_average_rate
@svc|extension/valuation.py|build_manual_valuation_lines build_manual_valuation_lines_series list_current_manual_valuation_facts
@svc|extension/market_data/service.py|sync_fx_rates sync_stock_prices ensure_market_data_fresh get_market_data_status resolve_missing_fx_rate
@svc|extension/scheduler.py|run_market_data_scheduler run_daily_market_data_sync
ingest_statement_price|svc|extension/ingest.py
@vo|base/contribution.py|ResolvedValuationContribution MarketValuationSelection
@svc|extension/valuation_contribution.py|resolve_valuation_contribution resolve_selected_market_valuation_contribution resolve_manual_valuation_contributions ManualValuationAttestationPolicy ResolvedMarketValuationPolicy
@vo|base/manual_valuation.py|ManualValuationComponentType ManualValuationLiquidityClass ManualValuationBasis ManualValuationFact
@ent|-|ManualValuationSnapshot MarketDataOverride
PriceSource|vo
@proj|-|LatestPriceView StalenessView
ObservationRepository|repo|base/repository.py|extension/repository.py
"""
    ),
    interface="""
Authority ExchangeRateLookup FxConversion FxRate FxWarning MARKET_DATA_QUANTITY_UNIT
MARKET_DATA_SYNC_TZ MarketDataOverride MarketDataScopeProvider MarketDataScopeStatus
MarketDataScopes MarketDataSyncResult MarketDataSyncState MarketValuationSelection
ManualValuationBasis ManualValuationAttestationPolicy ManualValuationComponentType
ManualValuationFact ManualValuationLiquidityClass NoObservationError
ObservationRepository ObservationSource PrefetchedFxRates PriceObservation
PriceObserved PriceSource PriceableSubject PricingError ResolutionPolicy
ResolvedMarketValuationPolicy ResolvedValuationContribution SqlObservationRepository
StatementPriceObservation StockPrice ValuationComponentItem
ValuationComponentsResult ValuationService ValuationServiceError
build_manual_valuation_lines build_manual_valuation_lines_series convert_amount
convert_money ensure_market_data_fresh get_average_rate get_exchange_rate
get_exchange_rate_series get_market_data_status ingest_statement_price
list_current_manual_valuation_facts next_market_data_sync_at record_manual_valuation
record_override pricing_trace_policy_registry resolve
resolve_manual_valuation_contributions
resolve_selected_market_valuation_contribution resolve_valuation_contribution
resolve_missing_fx_rate run_daily_market_data_sync run_market_data_scheduler
subscribe_price_ingest sync_fx_rates sync_stock_prices
""".split(),
    events="PriceObserved".split(),
    invariants=invs(
        """
@$t/test_pricing_package.py
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_AC_pricing_1_1_only_all_is_the_published_language
converges-by-layer|The package converges into base/ + extension/ + data/.|test_AC_pricing_1_2_converges_by_layer
base-layer-pure|Base/ never imports the package's own extension/ or data/, the ORM, or any network client.|test_AC_pricing_1_3_base_layer_is_pure
observations-are-append-only|PriceObservation rows are never updated or deleted in place.|test_AC_pricing_1_4_observations_are_append_only_by_construction
audit-never-looks-up-a-rate|Audit.money.convert takes a rate as an argument and performs no database lookup.|test_AC_pricing_1_5_audit_convert_takes_rate_as_argument
passes-own-governance-gate|Check_package_contract validates pricing with no violations.|test_AC_pricing_1_6_package_contract_gate_passes
"""
    ),
    roadmap=acs(
        "pricing",
        """
@$be/pricing/market_data/test_sync.py|P0
marketdata.1|Stock price sync fetches daily prices for active holdings and stores idempotent rows.|test_sync_stock_prices_inserts_missing_daily_rows_and_is_idempotent
marketdata.2|FX sync fetches explicit or observed pairs incrementally, with USD/base as the default non-empty pair.|test_sync_fx_rates_starts_after_last_stored_date
marketdata.3|Missing trading days are recorded as misses.|test_sync_stock_prices_records_missing_trading_days
marketdata.4|Primary and secondary providers are cross-validated and disagreements are not silently persisted.|test_stock_provider_disagreement_is_reported_without_persisting
marketdata.6|Portfolio valuation prefers synced stock prices over stale brokerage snapshots.|test_portfolio_uses_synced_stock_price_before_atomic_snapshot
marketdata.8|Long historical market data sync uses bounded range provider requests.|test_sync_stock_prices_fetches_decade_range_once
marketdata.9|Report reads check market data freshness and trigger at most one immediate refresh.|test_market_data_freshness_sync_runs_once_after_24h
@$e2e/test_market_data_price_paths.py|P0
marketdata.7|E2E gates cover provider-backed FX sync and stock-price portfolio valuation paths.|test_market_data_provider_sync_feeds_fx_and_stock_price_paths
marketdata.11|Staging E2E covers report-time market data refresh from an authenticated ordinary-user path.|test_market_data_provider_sync_feeds_fx_and_stock_price_paths
@$be/pricing/test_scheduler.py|P0
marketdata.10|Backend scheduler runs daily market data sync at the nightly Asia/Singapore close-refresh window.|test_next_market_data_sync_at_uses_nightly_sgt_schedule
marketdata.12|The daily crawl orchestrator syncs exactly the scopes an injected composition-root provider returns and commits once per run.|test_AC_pricing_marketdata_12_daily_sync_uses_injected_scope_provider
@$be/assets/test_manual_valuation_snapshots.py|P1
manualvaluation.1|Correcting a manual valuation appends a new version and preserves the prior fact unedited as a retrievable superseded version.|test_AC11_19_1_manual_valuation_correction_appends_version_and_preserves_history
manualvaluation.2|Heads-only reads use the current version.|test_AC11_19_2_corrected_valuation_is_not_double_counted_in_net_worth
provenance.1|Manual valuation component items expose a provenance field constrained to the shared Imported/Manual/Derived vocabulary.|test_AC22_13_1_valuation_component_item_uses_normalized_provenance_type
manualvaluation.5|POST/GET/PATCH /api/assets/valuation-snapshots records property value, mortgage/loan balance, CPF/long-term savings, tax payable/refund, insurance cash value, ESOP/RSU/options, source, notes, reminder cadence.|test_create_manual_valuation_snapshot_crud_api
manualvaluation.6|Latest manual valuation snapshots aggregate into asset/liability net-worth deltas with Decimal arithmetic.|test_manual_valuation_snapshot_latest_net_worth_components
manualvaluation.7|Restricted and illiquid manual-valuation components are tagged separately and can be excluded from liquid net-worth views.|test_manual_valuation_snapshot_restricted_toggle
@$be/pricing/test_valuation_lines.py|P1
manualvaluation.3|Manual-valuation balance-sheet lines are built by pricing.|test_AC_pricing_manualvaluation_3_lines_split_convert_and_classify
manualvaluation.4|A combination whose only snapshot postdates the requested as_of_date is absent from the valuation components and lines.|test_AC_pricing_manualvaluation_4_component_recorded_after_as_of_is_warned
manualvaluation.11|Build_manual_valuation_lines_series returns, for each requested date, the lines of build_manual_valuation_lines on that date.|test_AC_pricing_manualvaluation_11_series_equals_one_build_per_date
@$be/pricing/test_valuation_liquidity_contract.py|P0
manualvaluation.12|Split_net_worth_scope is the one definition of the restricted-holdings scope.|test_AC_pricing_manualvaluation_12_scope_excludes_a_liability_with_its_asset
manualvaluation.13|Build_manual_valuation_lines keeps a pricing-family FX error on an excluded component as a line.|test_AC_pricing_manualvaluation_13_excluded_line_errors_by_type|P1
@$be/pricing/test_fx.py|P1
fx.1|Get_average_rate falls back to the period-end spot rate.|test_AC_pricing_fx_1_average_rate_fallback_appends_fx_warning
fx.2|PrefetchedFxRates batch-prefetches spot and average-window rates under distinct keys, serves the identity rate.|test_AC_pricing_fx_2_prefetch_serves_spot_and_average_keys
fx.4|Get_exchange_rate_series returns, for each requested date, the get_exchange_rate result on that date and omits a date.|test_AC_pricing_fx_4_rate_series_equals_one_lookup_per_date
fx.6|Get_exchange_rate and get_exchange_rate_series do not let an earlier lazily derived inverse FX row hide a newer stored inverse rate on a later date.|test_AC_pricing_fx_6_derived_inverse_rate_does_not_shadow_newer_inverse_rate
@$be/pricing/market_data/test_provider_parsers.py|P1
providers.2|_looks_like_ticker accepts real tickers/FX pairs and rejects fund-name free text.|test_looks_like_ticker_accepts_real_tickers_rejects_free_text
providers.3|A non-ticker identifier short-circuits the Yahoo stock fetch with no HTTP call.|test_yahoo_stock_fetch_short_circuits_for_non_ticker
providers.4|HK numeric exchange codes map to the Yahoo <4-digit>.HK symbol.|test_AC17_33_1_yahoo_stock_symbol_maps_hk_numeric_codes
providers.5|HK numeric codes resolve to the Stooq <4-digit>.hk symbol.|test_AC17_33_2_stooq_stock_symbol_maps_hk_numeric_codes
@$be/pricing/test_ingest.py|P0
ingest.1|An extraction-published PriceObserved dispatched by the outbox relay results in exactly one pricing observation with correct fields and the extraction fact id carried as provenance.|test_AC_pricing_ingest_1_extraction_event_lands_as_one_provenanced_observation
ingest.2|Ingest is idempotent under at-least-once delivery.|test_AC_pricing_ingest_2_redelivery_through_the_relay_does_not_duplicate
ingest.3|An ingested statement observation is a first-class, user-scoped resolve candidate.|test_AC_pricing_ingest_3_ingested_observation_is_resolvable
@$fe/__tests__/useCurrencies.test.tsx|P2
fe-currencies.1|`useCurrencies` returns default currencies while loading.|AC16.9.1 returns default currencies while loading
fe-currencies.2|`useCurrencies` updates currencies from API response.|AC16.9.2 updates currencies from API response
fe-currencies.3|`useCurrencies` falls back to defaults on API error.|AC16.9.3 falls back to defaults when API returns empty array
@$be/pricing/test_resolved_valuation_contribution.py|P0
valuation-contribution.1|Recording or correcting a manual valuation appends its immutable observation and a current, target-matching TraceRecord decision in the same caller-owned transaction.|test_AC_pricing_valuation_contribution_1_manual_write_emits_and_supersedes_decision
valuation-contribution.2|Resolve_valuation_contribution returns the exact selected observation identity/version, resolution policy.|test_AC_pricing_valuation_contribution_2_resolve_pins_exact_observation_and_decision
valuation-contribution.3|An absent, stale, rejected, superseded, cross-tenant, or target-mismatched valuation decision returns an explicit unproven contribution.|test_AC_pricing_valuation_contribution_3_missing_or_stale_decision_is_unproven
valuation-contribution.4|Rolling back a manual valuation write leaves neither the valuation row nor its TraceRecord observation/decision durable.|test_AC_pricing_valuation_contribution_4_rollback_is_atomic
valuation-contribution.5|Pricing resolves every current manual valuation lineage into the same ResolvedValuationContribution shape.|test_AC_pricing_valuation_contribution_5_resolves_each_manual_lineage_without_shadow_trust
valuation-contribution.6|A report schedule can name one selected market observation only.|test_AC_pricing_valuation_contribution_6_selected_market_input_requires_exact_schedule_observation
@-|P1
marketdata.5|Market data sync endpoints expose FX and stock sync status for scheduler/E2E callers.|$be/market_data/test_sync_router.py::test_market_data_sync_endpoints_return_counts|P0
marketdata.13|The real FX/market-data path proves an exact converted VALUE in the blocking lane.|$be/pricing/market_data/test_recorded_provider_price_path.py::test_recorded_provider_fx_and_stock_path_converts_exactly|P0:exact
fx.3|Convert_amount/convert_money honor an average-rate window with the same period-end fallback + fx_warnings semantics as the spot path.|$be/pricing/test_convert.py::test_AC_pricing_fx_3_convert_amount_uses_average_rate_window
fx.5|ExchangeRateLookup in apps/backend/src/pricing/extension/fx.py is the one FX rate-lookup Protocol in apps/backend/src.|$t/test_single_fx_rate_port.py::test_AC_pricing_fx_5_exchange_rate_lookup_is_the_one_fx_rate_port
providers.1|A manual price update creates a MarketDataOverride record for the given asset/date, independent of provider sync.|$be/portfolio/test_portfolio_service.py::test_update_prices_happy
manualvaluation.8|A manual valuation correction with a structured valuation_basis appends a new immutable head and supersedes the unsubstantiated version.|$be/assets/test_manual_valuation_basis.py::test_AC11_9_5_structured_basis_supersedes_the_unsubstantiated_head
manualvaluation.9|The package traceability appendix surfaces each manual valuation snapshot's structured valuation_basis in its source-anchor detail.|$be/api/test_personal_report_package_contract.py::test_AC11_9_10_package_traceability_surfaces_manual_valuation_basis
manualvaluation.10|ManualValuationSnapshot and its valuation vocabulary are pricing-owned.|$be/pricing/test_manual_valuation_ownership.py::test_AC_pricing_manualvaluation_10_pricing_owns_the_manual_valuation_mapping|P0
fe-settings.1|The frontend General Settings page exposes a "Base currency" control that reads + updates the effective value.|$fe/__tests__/generalSettingsPage.test.tsx::AC12.39.3 renders the effective base currency and keeps Save disabled until edited
""",
    ),
    concepts=concepts(
        """
market_data|common/pricing/readme.md#market-data-pre-1610-cutover-shipped-model|FX rates, stock prices, data sources, and sync schedule. Legacy model; internalized into the pricing package readme (migration closeout wave 3, #1664); consolidates into the unified observation model at the #1610 consumer-wiring cutover.|common/pricing/market_data.md,common/reporting/reporting.md,common/pricing/contract.py|-|market|concept
net_worth_valuation_snapshots|common/pricing/readme.md#manual-valuation-snapshots|Point-in-time manual valuation snapshots for non-ledger net worth components. Legacy model; retires into the pricing package's unified observation model (#1610) at the consumer-wiring cutover (internalized into the package readme itself, migration closeout wave 3, #1664).|common/portfolio/assets.md,common/reporting/reporting.md,common/pricing/contract.py,common/meta/schema.md|-|assets|concept
"""
    ),
)
