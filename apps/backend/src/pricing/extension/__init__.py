"""``pricing.extension`` — the domain services + impure edges.

Real this commit: ``resolve()`` (implementation-pure — no I/O — but
``KIND_LAYER`` places every ``DOMAIN_SERVICE`` in ``extension/`` with no
exception, so it lives here despite touching no database),
``SqlObservationRepository`` (the read-only adapter over the 4 legacy
tables), the two user-scoped write recorders
(``record_manual_valuation``/``record_override``), and
``get_exchange_rate`` + the ``convert_*`` trio + ``get_average_rate`` (thin
FX-specific wrappers over the same subject+resolve path — caching and the
crawler lazy-fallback are deliberately deferred, see ``extension/fx.py``).

Reserved for a later commit: crawler sync (``services/market_data/``) and
the ``extraction`` ``PriceObserved``-ingest subscriber. See
``common/pricing/contract.py`` — these are declared as taxonomy-only
reserved units (no module path) until then.
"""

from __future__ import annotations

from src.pricing.extension.fx import (
    convert_amount,
    convert_money,
    convert_to_base,
    get_average_rate,
    get_exchange_rate,
)
from src.pricing.extension.manual import record_manual_valuation, record_override
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve

__all__ = [
    "SqlObservationRepository",
    "convert_amount",
    "convert_money",
    "convert_to_base",
    "get_average_rate",
    "get_exchange_rate",
    "record_manual_valuation",
    "record_override",
    "resolve",
]
