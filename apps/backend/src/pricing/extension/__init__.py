"""``pricing.extension`` — the domain services + impure edges.

Real here: ``resolve()`` (implementation-pure — no I/O — but
``KIND_LAYER`` places every ``DOMAIN_SERVICE`` in ``extension/`` with no
exception, so it lives here despite touching no database),
``SqlObservationRepository`` (the read adapter over the 4 legacy
tables + the ingest store), the two user-scoped write recorders
(``record_manual_valuation``/``record_override``), the ``extraction``
``PriceObserved``-ingest subscriber (``extension/ingest.py`` —
``ingest_statement_price`` + the ``subscribe_price_ingest`` wiring the app
composition root calls, #1642), the full FX lookup surface absorbed from
``services/fx.py`` (#1610 P2 — ``get_exchange_rate`` + the ``convert_*``
trio + ``get_average_rate`` with the ``fx_warnings`` side-channel and
average-rate windows, plus ``PrefetchedFxRates``; see ``extension/fx.py``),
the manual-valuation balance-sheet line builder
(``build_manual_valuation_lines``, absorbed from
``services/reporting/manual_valuation.py``), the crawler sync
(``extension/market_data/`` — ``sync_fx_rates``/``sync_stock_prices``/
``ensure_market_data_fresh``/``get_market_data_status``/
``resolve_missing_fx_rate``; the many crawler-internal names in that
subpackage's own ``__all__`` stay package-internal and are deliberately NOT
flattened here, the same way ``reconciliation.extension.phases`` never
bubbles up to ``reconciliation``'s top level), and the daily crawl
orchestrator (``extension/scheduler.py``, absorbed from
``services/market_data_scheduler.py`` — scope discovery stays inverted
behind the composition root's :data:`MarketDataScopeProvider`).
"""

from __future__ import annotations

from src.pricing.extension.fx import (
    FxWarning,
    PrefetchedFxRates,
    convert_amount,
    convert_money,
    convert_to_base,
    get_average_rate,
    get_exchange_rate,
)
from src.pricing.extension.ingest import ingest_statement_price, subscribe_price_ingest
from src.pricing.extension.manual import record_manual_valuation, record_override
from src.pricing.extension.market_data import (
    MARKET_DATA_QUANTITY_UNIT,
    MarketDataScopeStatus,
    MarketDataSyncResult,
    ensure_market_data_fresh,
    get_market_data_status,
    resolve_missing_fx_rate,
    sync_fx_rates,
    sync_stock_prices,
)
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve
from src.pricing.extension.scheduler import (
    MARKET_DATA_SYNC_TZ,
    MarketDataScopeProvider,
    MarketDataScopes,
    next_market_data_sync_at,
    run_daily_market_data_sync,
    run_market_data_scheduler,
)
from src.pricing.extension.valuation_contribution import (
    ManualValuationAttestationPolicy,
    ResolvedMarketValuationPolicy,
    ResolvedValuationContribution,
    pricing_trace_policy_registry,
    resolve_manual_valuation_contributions,
    resolve_selected_market_valuation_contribution,
    resolve_valuation_contribution,
)

__all__ = [
    "FxWarning",
    "MARKET_DATA_QUANTITY_UNIT",
    "MARKET_DATA_SYNC_TZ",
    "MarketDataScopeProvider",
    "MarketDataScopeStatus",
    "MarketDataScopes",
    "MarketDataSyncResult",
    "ManualValuationAttestationPolicy",
    "PrefetchedFxRates",
    "SqlObservationRepository",
    "convert_amount",
    "convert_money",
    "convert_to_base",
    "ensure_market_data_fresh",
    "get_average_rate",
    "get_exchange_rate",
    "get_market_data_status",
    "ingest_statement_price",
    "next_market_data_sync_at",
    "record_manual_valuation",
    "record_override",
    "ResolvedValuationContribution",
    "ResolvedMarketValuationPolicy",
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
