"""PackageContract for ``pricing``."""

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
ObservationRepository ObservationSource PrefetchedFxRates PriceObservation PriceObserved
PriceSource PriceableSubject PricingError ResolutionPolicy ResolvedMarketValuationPolicy
ResolvedValuationContribution SqlObservationRepository StatementPriceObservation
StockPrice ValuationComponentItem ValuationComponentsResult ValuationService
ValuationServiceError build_manual_valuation_lines build_manual_valuation_lines_series
convert_amount convert_money ensure_market_data_fresh get_average_rate get_exchange_rate
get_exchange_rate_series get_market_data_status ingest_statement_price
list_current_manual_valuation_facts next_market_data_sync_at record_manual_valuation
record_override pricing_trace_policy_registry resolve
resolve_manual_valuation_contributions resolve_selected_market_valuation_contribution
resolve_valuation_contribution resolve_missing_fx_rate run_daily_market_data_sync
run_market_data_scheduler subscribe_price_ingest sync_fx_rates sync_stock_prices
""".split(),
    events=["PriceObserved"],
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
@$be/pricing/market_data/test_sync.py
marketdata.1||test_sync_stock_prices_inserts_missing_daily_rows_and_is_idempotent
marketdata.2||test_sync_fx_rates_starts_after_last_stored_date
marketdata.3||test_sync_stock_prices_records_missing_trading_days
marketdata.4||test_stock_provider_disagreement_is_reported_without_persisting
marketdata.6||test_portfolio_uses_synced_stock_price_before_atomic_snapshot
marketdata.8||test_sync_stock_prices_fetches_decade_range_once
marketdata.9||test_market_data_freshness_sync_runs_once_after_24h
@$e2e/test_market_data_price_paths.py
marketdata.7|E2E gates cover provider-backed FX sync and stock-price portfolio valuation paths.|test_market_data_provider_sync_feeds_fx_and_stock_price_paths
marketdata.11|Staging E2E covers report-time market data refresh from an authenticated ordinary-user path.|^
@$be/pricing/test_scheduler.py
marketdata.10||test_next_market_data_sync_at_uses_nightly_sgt_schedule
marketdata.12||test_AC_pricing_marketdata_12_daily_sync_uses_injected_scope_provider
@$be/assets/test_manual_valuation_snapshots.py|P1
manualvaluation.1||test_AC11_19_1_manual_valuation_correction_appends_version_and_preserves_history
manualvaluation.2||test_AC11_19_2_corrected_valuation_is_not_double_counted_in_net_worth
provenance.1||test_AC22_13_1_valuation_component_item_uses_normalized_provenance_type
manualvaluation.5||test_create_manual_valuation_snapshot_crud_api
manualvaluation.6||test_manual_valuation_snapshot_latest_net_worth_components
manualvaluation.7||test_manual_valuation_snapshot_restricted_toggle
@$be/pricing/test_valuation_lines.py|P1
manualvaluation.3||test_AC_pricing_manualvaluation_3_lines_split_convert_and_classify
manualvaluation.4||test_AC_pricing_manualvaluation_4_component_recorded_after_as_of_is_warned
manualvaluation.11||test_AC_pricing_manualvaluation_11_series_equals_one_build_per_date
@$be/pricing/test_valuation_liquidity_contract.py
manualvaluation.12||test_AC_pricing_manualvaluation_12_scope_excludes_a_liability_with_its_asset
manualvaluation.13||test_AC_pricing_manualvaluation_13_excluded_line_errors_by_type|P1
@$be/pricing/test_fx.py|P1
fx.1||test_AC_pricing_fx_1_average_rate_fallback_appends_fx_warning
fx.2||test_AC_pricing_fx_2_prefetch_serves_spot_and_average_keys
fx.4||test_AC_pricing_fx_4_rate_series_equals_one_lookup_per_date
fx.6||test_AC_pricing_fx_6_derived_inverse_rate_does_not_shadow_newer_inverse_rate
@$be/pricing/market_data/test_provider_parsers.py|P1
providers.2||test_looks_like_ticker_accepts_real_tickers_rejects_free_text
providers.3||test_yahoo_stock_fetch_short_circuits_for_non_ticker
providers.4||test_AC17_33_1_yahoo_stock_symbol_maps_hk_numeric_codes
providers.5||test_AC17_33_2_stooq_stock_symbol_maps_hk_numeric_codes
@$be/pricing/test_ingest.py
ingest.1||test_AC_pricing_ingest_1_extraction_event_lands_as_one_provenanced_observation
ingest.2||test_AC_pricing_ingest_2_redelivery_through_the_relay_does_not_duplicate
ingest.3||test_AC_pricing_ingest_3_ingested_observation_is_resolvable
@$fe/__tests__/useCurrencies.test.tsx|P2
fe-currencies.1||AC16.9.1 returns default currencies while loading
fe-currencies.2||AC16.9.2 updates currencies from API response
fe-currencies.3||AC16.9.3 falls back to defaults when API returns empty array
@$be/pricing/test_resolved_valuation_contribution.py
valuation-contribution.1||test_AC_pricing_valuation_contribution_1_manual_write_emits_and_supersedes_decision
valuation-contribution.2||test_AC_pricing_valuation_contribution_2_resolve_pins_exact_observation_and_decision
valuation-contribution.3||test_AC_pricing_valuation_contribution_3_missing_or_stale_decision_is_unproven
valuation-contribution.4||test_AC_pricing_valuation_contribution_4_rollback_is_atomic
valuation-contribution.5||test_AC_pricing_valuation_contribution_5_resolves_each_manual_lineage_without_shadow_trust
valuation-contribution.6||test_AC_pricing_valuation_contribution_6_selected_market_input_requires_exact_schedule_observation
@$be/market_data/test_sync_router.py
marketdata.5||test_market_data_sync_endpoints_return_counts
@$be/pricing/market_data/test_recorded_provider_price_path.py
marketdata.13||test_recorded_provider_fx_and_stock_path_converts_exactly
@$be/pricing/test_convert.py|P1
fx.3||test_AC_pricing_fx_3_convert_amount_uses_average_rate_window
@$t/test_single_fx_rate_port.py|P1
fx.5||test_AC_pricing_fx_5_exchange_rate_lookup_is_the_one_fx_rate_port
@$be/portfolio/test_portfolio_service.py|P1
providers.1||test_update_prices_happy
@$be/assets/test_manual_valuation_basis.py|P1
manualvaluation.8||test_AC11_9_5_structured_basis_supersedes_the_unsubstantiated_head
@$be/api/test_personal_report_package_contract.py|P1
manualvaluation.9||test_AC11_9_10_package_traceability_surfaces_manual_valuation_basis
@$be/pricing/test_manual_valuation_ownership.py
manualvaluation.10||test_AC_pricing_manualvaluation_10_pricing_owns_the_manual_valuation_mapping
@$fe/__tests__/generalSettingsPage.test.tsx|P1
fe-settings.1||AC12.39.3 renders the effective base currency and keeps Save disabled until edited
""",
    ),
    concepts=concepts(
        """
market_data|common/pricing/readme.md#market-data-pre-1610-cutover-shipped-model|FX rates, stock prices, data sources, and sync schedule.|common/pricing/market_data.md,common/reporting/reporting.md,common/pricing/contract.py|-|market|concept
net_worth_valuation_snapshots|common/pricing/readme.md#manual-valuation-snapshots|Point-in-time manual valuation snapshots for non-ledger net worth components.|common/portfolio/assets.md,common/reporting/reporting.md,common/pricing/contract.py,common/meta/schema.md|-|assets|concept
"""
    ),
)
