"""``pricing.extension`` — the domain services + impure edges.

``resolve()`` is this commit's one real symbol here: it is implementation-pure
(no I/O), but ``KIND_LAYER`` places every ``DOMAIN_SERVICE`` in ``extension/``
with no exception, so it lives here despite touching no database.

Everything else is reserved for the commit that moves the actual logic in:
crawler adapters (``services/market_data/``), manual entry + override
recording (the valuation slice of ``services/assets.py``), FX rate lookup (the
lookup half of ``services/fx.py``), and the ``extraction``
``PriceObserved``-ingest subscriber, plus the ``ObservationRepository``
adapter. See ``common/pricing/contract.py`` — these are declared as
taxonomy-only reserved units (no module path) until then.
"""

from __future__ import annotations

from src.pricing.extension.resolve import resolve

__all__ = ["resolve"]
