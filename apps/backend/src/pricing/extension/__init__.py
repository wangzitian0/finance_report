"""``pricing.extension`` — the domain services + impure edges.

Real this commit: ``resolve()`` (implementation-pure — no I/O — but
``KIND_LAYER`` places every ``DOMAIN_SERVICE`` in ``extension/`` with no
exception, so it lives here despite touching no database) and
``SqlObservationRepository`` (the read-only adapter over the 4 legacy
tables — ``FxRate``/``StockPrice``/``MarketDataOverride``/
``ManualValuationSnapshot``).

The write-side domain services are reserved for the commit that moves the
actual logic in: crawler adapters (``services/market_data/``), manual entry +
override *recording* (the valuation slice of ``services/assets.py`` — reading
is already wired via the repository above), FX rate lookup (the lookup half
of ``services/fx.py``), and the ``extraction`` ``PriceObserved``-ingest
subscriber. See ``common/pricing/contract.py`` — these are declared as
taxonomy-only reserved units (no module path) until then.
"""

from __future__ import annotations

from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve

__all__ = ["SqlObservationRepository", "resolve"]
