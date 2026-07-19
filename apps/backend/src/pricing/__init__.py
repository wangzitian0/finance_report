"""``pricing`` — the backend implementation of the ``pricing`` package (#1610).

The price/valuation **observation + resolution** SSOT (design review
2026-07-06): *an observation that a subject was worth X at time T, from a
source, with an authority rank — plus the resolution policy for conflicting
observations*. See ``common/pricing/contract.py`` for the full model and the
boundary rulings (FX split with audit, the extraction event-ingest boundary,
bitemporal semantics, append-only overrides).

This package ships the pure ``base/`` layer (subject identity, the
append-only ``PriceObservation`` aggregate, the repository port),
``resolve()`` (implementation-pure, physically in ``extension/`` per
``KIND_LAYER``), ``SqlObservationRepository`` (a read-only adapter over the
4 legacy tables — schema-preserving on purpose: the physical store keeps the
legacy shapes while every read already goes through the unified
subject+resolve path), the two user-scoped write recorders
(``record_manual_valuation``/``record_override`` — each also publishes
``PriceObserved`` through the platform outbox, atomically with the write),
the full FX lookup surface absorbed from the retired ``services/fx.py``
(#1610 P2 — ``get_exchange_rate`` + the ``convert_*`` trio +
``get_average_rate`` with ``fx_warnings``/average-window parity, plus
``PrefetchedFxRates``), the manual-valuation balance-sheet line builder
(``build_manual_valuation_lines``, absorbed from
``services/reporting/manual_valuation.py``), the crawler sync
(``sync_fx_rates``/``sync_stock_prices``/``ensure_market_data_fresh``/
``get_market_data_status``/``resolve_missing_fx_rate`` — pure "given these
scopes, sync/report on them"; discovering *which* scopes from the user's
ledger is the caller's job, see ``extension/market_data/service.py``), the
daily crawl orchestrator (``run_market_data_scheduler`` — scopes injected by
the composition root's :data:`MarketDataScopeProvider`, absorbed from
``services/market_data_scheduler.py``), and the extraction-event ingest
subscriber (``ingest_statement_price`` + ``subscribe_price_ingest``, #1642 —
the first cross-domain event consumer; see ``extension/ingest.py``). The
``data/`` projections remain reserved (declared in the contract's ``units``
with no module path) for a later commit.
"""

from __future__ import annotations

from src.pricing.base import (
    Authority,
    ObservationRepository,
    ObservationSource,
    PriceableSubject,
    PriceObservation,
    PriceObserved,
    PricingError,
    ResolutionPolicy,
)
from src.pricing.base.contribution import MarketValuationSelection
from src.pricing.base.manual_valuation import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationFact,
    ManualValuationLiquidityClass,
)
from src.pricing.extension import (
    MARKET_DATA_QUANTITY_UNIT,
    MARKET_DATA_SYNC_TZ,
    FxWarning,
    ManualValuationAttestationPolicy,
    MarketDataScopeProvider,
    MarketDataScopes,
    MarketDataScopeStatus,
    MarketDataSyncResult,
    PrefetchedFxRates,
    ResolvedMarketValuationPolicy,
    ResolvedValuationContribution,
    SqlObservationRepository,
    convert_amount,
    convert_money,
    convert_to_base,
    ensure_market_data_fresh,
    get_average_rate,
    get_exchange_rate,
    get_market_data_status,
    ingest_statement_price,
    list_current_manual_valuation_facts,
    next_market_data_sync_at,
    pricing_trace_policy_registry,
    record_manual_valuation,
    record_override,
    resolve,
    resolve_manual_valuation_contributions,
    resolve_missing_fx_rate,
    resolve_selected_market_valuation_contribution,
    resolve_valuation_contribution,
    run_daily_market_data_sync,
    run_market_data_scheduler,
    subscribe_price_ingest,
    sync_fx_rates,
    sync_stock_prices,
)
from src.pricing.extension.valuation import (
    ValuationComponentItem,
    ValuationComponentsResult,
    ValuationService,
    ValuationServiceError,
    build_manual_valuation_lines,
)

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly so importing the package registers the mappers on Base.metadata.
from src.pricing.orm.fx_conversion import FxConversion
from src.pricing.orm.manual_valuation import ManualValuationSnapshot  # noqa: F401  (mapper registration)
from src.pricing.orm.market_data import FxRate, MarketDataSyncState, StockPrice
from src.pricing.orm.market_data_override import MarketDataOverride, PriceSource
from src.pricing.orm.statement_observation import StatementPriceObservation

__all__ = [
    "Authority",
    "FxConversion",
    "FxRate",
    "FxWarning",
    "MARKET_DATA_QUANTITY_UNIT",
    "MARKET_DATA_SYNC_TZ",
    "MarketDataOverride",
    "MarketDataScopeProvider",
    "MarketDataScopeStatus",
    "MarketDataScopes",
    "MarketDataSyncResult",
    "ManualValuationBasis",
    "ManualValuationAttestationPolicy",
    "ManualValuationComponentType",
    "ManualValuationFact",
    "ManualValuationLiquidityClass",
    "MarketDataSyncState",
    "MarketValuationSelection",
    "ObservationRepository",
    "ObservationSource",
    "PrefetchedFxRates",
    "PriceObservation",
    "PriceObserved",
    "PriceSource",
    "PriceableSubject",
    "PricingError",
    "ResolutionPolicy",
    "ResolvedValuationContribution",
    "ResolvedMarketValuationPolicy",
    "SqlObservationRepository",
    "StatementPriceObservation",
    "StockPrice",
    "ValuationComponentItem",
    "ValuationComponentsResult",
    "ValuationService",
    "ValuationServiceError",
    "build_manual_valuation_lines",
    "convert_amount",
    "convert_money",
    "convert_to_base",
    "ensure_market_data_fresh",
    "get_average_rate",
    "get_exchange_rate",
    "get_market_data_status",
    "ingest_statement_price",
    "list_current_manual_valuation_facts",
    "next_market_data_sync_at",
    "record_manual_valuation",
    "record_override",
    "resolve",
    "resolve_manual_valuation_contributions",
    "resolve_selected_market_valuation_contribution",
    "resolve_valuation_contribution",
    "resolve_missing_fx_rate",
    "run_daily_market_data_sync",
    "run_market_data_scheduler",
    "pricing_trace_policy_registry",
    "subscribe_price_ingest",
    "sync_fx_rates",
    "sync_stock_prices",
]
