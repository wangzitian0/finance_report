"""``pricing`` — the backend implementation of the ``pricing`` package (#1610).

The price/valuation **observation + resolution** SSOT (design review
2026-07-06): *an observation that a subject was worth X at time T, from a
source, with an authority rank — plus the resolution policy for conflicting
observations*. See ``common/pricing/contract.py`` for the full model and the
boundary rulings (FX split with audit, the extraction event-ingest boundary,
bitemporal semantics, append-only overrides).

This commit ships the pure ``base/`` layer (subject identity, the append-only
``PriceObservation`` aggregate, the repository port), ``resolve()``
(implementation-pure, physically in ``extension/`` per ``KIND_LAYER``),
``SqlObservationRepository`` (a read-only adapter over the 4 legacy tables —
schema-preserving on purpose, so it can land ahead of unifying them into one
physical store), the two user-scoped write recorders
(``record_manual_valuation``/``record_override`` — each also publishes
``PriceObserved`` through the platform outbox, atomically with the write),
``get_exchange_rate`` + the ``convert_*`` trio + ``get_average_rate`` (thin
FX-specific wrappers over the same subject+resolve path), and the crawler
sync (``sync_fx_rates``/``sync_stock_prices``/``ensure_market_data_fresh``/
``get_market_data_status``/``resolve_missing_fx_rate`` — pure "given these
scopes, sync/report on them"; discovering *which* scopes from the user's
ledger is the caller's job, see ``extension/market_data/service.py``). The
remaining ``extension/`` domain service (the extraction-event subscriber)
and the ``data/`` projections are reserved (declared in the contract's
``units`` with no module path) for a later commit.
"""

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly and FIRST so a re-entrant circular import finds them bound, and so
# importing the package registers the mappers on Base.metadata.
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
from src.pricing.extension import (
    MARKET_DATA_QUANTITY_UNIT,
    MarketDataScopeStatus,
    MarketDataSyncResult,
    SqlObservationRepository,
    convert_amount,
    convert_money,
    convert_to_base,
    ensure_market_data_fresh,
    get_average_rate,
    get_exchange_rate,
    get_market_data_status,
    record_manual_valuation,
    record_override,
    resolve,
    resolve_missing_fx_rate,
    sync_fx_rates,
    sync_stock_prices,
)
from src.pricing.orm.market_data import FxRate, MarketDataSyncState, StockPrice

__all__ = [
    "Authority",
    "FxRate",
    "MARKET_DATA_QUANTITY_UNIT",
    "MarketDataScopeStatus",
    "MarketDataSyncResult",
    "MarketDataSyncState",
    "ObservationRepository",
    "ObservationSource",
    "PriceObservation",
    "PriceObserved",
    "PriceableSubject",
    "PricingError",
    "ResolutionPolicy",
    "SqlObservationRepository",
    "StockPrice",
    "convert_amount",
    "convert_money",
    "convert_to_base",
    "ensure_market_data_fresh",
    "get_average_rate",
    "get_exchange_rate",
    "get_market_data_status",
    "record_manual_valuation",
    "record_override",
    "resolve",
    "resolve_missing_fx_rate",
    "sync_fx_rates",
    "sync_stock_prices",
]
