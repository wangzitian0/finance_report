"""``pricing.extension`` — the domain services + impure edges.

Real this commit: ``resolve()`` (implementation-pure — no I/O — but
``KIND_LAYER`` places every ``DOMAIN_SERVICE`` in ``extension/`` with no
exception, so it lives here despite touching no database),
``SqlObservationRepository`` (the read-only adapter over the 4 legacy
tables), the two user-scoped write recorders
(``record_manual_valuation``/``record_override``), and
``get_exchange_rate`` (a thin FX-specific wrapper over the same
subject+resolve path — caching and the crawler lazy-fallback are
deliberately deferred, see ``extension/fx.py``).

Reserved for a later commit: crawler sync (``services/market_data/``) and
the ``extraction`` ``PriceObserved``-ingest subscriber. See
``common/pricing/contract.py`` — these are declared as taxonomy-only
reserved units (no module path) until then.
"""

from __future__ import annotations

from src.pricing.extension.fx import get_exchange_rate
from src.pricing.extension.manual import record_manual_valuation, record_override
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve

__all__ = [
    "SqlObservationRepository",
    "get_exchange_rate",
    "record_manual_valuation",
    "record_override",
    "resolve",
]
