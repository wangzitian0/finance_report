"""``pricing`` — the backend implementation of the ``pricing`` package (#1610).

The price/valuation **observation + resolution** SSOT (design review
2026-07-06): *an observation that a subject was worth X at time T, from a
source, with an authority rank — plus the resolution policy for conflicting
observations*. See ``common/pricing/contract.py`` for the full model and the
boundary rulings (FX split with audit, the extraction event-ingest boundary,
bitemporal semantics, append-only overrides).

This commit ships the pure ``base/`` layer only (subject identity, the
append-only ``PriceObservation`` aggregate, the ``resolve()`` domain service,
the repository port) — real and tested, but not yet wired to storage. The
``extension/`` domain services (crawler sync, manual entry/override, FX rate
lookup, the extraction-event subscriber) and the ``data/`` projections are
reserved (declared in the contract's ``units`` with no module path) for the
commit that moves ``fx.py``/``market_data``/``assets.py``'s actual logic in.
"""

from __future__ import annotations

from src.pricing.base import (
    Authority,
    ObservationSource,
    PriceableSubject,
    PriceObservation,
    PriceObserved,
    PricingError,
    ResolutionPolicy,
)
from src.pricing.extension import resolve

__all__ = [
    "Authority",
    "ObservationSource",
    "PriceObservation",
    "PriceObserved",
    "PriceableSubject",
    "PricingError",
    "ResolutionPolicy",
    "resolve",
]
