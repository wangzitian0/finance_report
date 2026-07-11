"""``pricing.extension`` — the domain services + impure edges.

Real here: ``resolve()`` (implementation-pure — no I/O — but
``KIND_LAYER`` places every ``DOMAIN_SERVICE`` in ``extension/`` with no
exception, so it lives here despite touching no database),
``SqlObservationRepository`` (the read adapter over the 4 legacy
tables + the ingest store), the two user-scoped write recorders
(``record_manual_valuation``/``record_override``), the ``extraction``
``PriceObserved``-ingest subscriber (``extension/ingest.py`` —
``ingest_statement_price`` + the ``subscribe_price_ingest`` wiring the app
composition root calls, #1642), ``get_exchange_rate`` +
the ``convert_*`` trio + ``get_average_rate`` (thin FX-specific wrappers over
the same subject+resolve path — caching and the crawler lazy-fallback are
deliberately deferred, see ``extension/fx.py``), and the crawler sync
(``extension/market_data/`` — ``sync_fx_rates``/``sync_stock_prices``/
``ensure_market_data_fresh``/``get_market_data_status``/
``resolve_missing_fx_rate``; the many crawler-internal names in that
subpackage's own ``__all__`` stay package-internal and are deliberately NOT
flattened here, the same way ``reconciliation.extension.phases`` never
bubbles up to ``reconciliation``'s top level).
"""

from __future__ import annotations

from src.pricing.extension.fx import (
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

__all__ = [
    "MARKET_DATA_QUANTITY_UNIT",
    "MarketDataScopeStatus",
    "MarketDataSyncResult",
    "SqlObservationRepository",
    "convert_amount",
    "convert_money",
    "convert_to_base",
    "ensure_market_data_fresh",
    "get_average_rate",
    "get_exchange_rate",
    "get_market_data_status",
    "ingest_statement_price",
    "record_manual_valuation",
    "record_override",
    "resolve",
    "resolve_missing_fx_rate",
    "subscribe_price_ingest",
    "sync_fx_rates",
    "sync_stock_prices",
]
