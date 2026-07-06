"""``pricing.extension`` — the domain services + impure edges.

Real this commit: ``resolve()`` (implementation-pure — no I/O — but
``KIND_LAYER`` places every ``DOMAIN_SERVICE`` in ``extension/`` with no
exception, so it lives here despite touching no database),
``SqlObservationRepository`` (the read-only adapter over the 4 legacy
tables), and the two user-scoped write recorders
(``record_manual_valuation``/``record_override``) that persist into
``ManualValuationSnapshot``/``MarketDataOverride`` — the same tables the
repository reads back uniformly.

Reserved for a later commit: crawler sync (``services/market_data/``), FX
rate lookup (the lookup half of ``services/fx.py``), and the ``extraction``
``PriceObserved``-ingest subscriber. See ``common/pricing/contract.py`` —
these are declared as taxonomy-only reserved units (no module path) until
then.
"""

from __future__ import annotations

from src.pricing.extension.manual import record_manual_valuation, record_override
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve

__all__ = [
    "SqlObservationRepository",
    "record_manual_valuation",
    "record_override",
    "resolve",
]
