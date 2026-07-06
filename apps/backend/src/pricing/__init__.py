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
and ``get_exchange_rate`` + the ``convert_*`` trio + ``get_average_rate``
(thin FX-specific wrappers over the same subject+resolve path). The
remaining ``extension/`` domain services (crawler sync, the extraction-event
subscriber) and the ``data/`` projections are reserved (declared in the
contract's ``units`` with no module path) for a later commit.
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
from src.pricing.extension import (
    SqlObservationRepository,
    convert_amount,
    convert_money,
    convert_to_base,
    get_average_rate,
    get_exchange_rate,
    record_manual_valuation,
    record_override,
    resolve,
)

__all__ = [
    "Authority",
    "ObservationRepository",
    "ObservationSource",
    "PriceObservation",
    "PriceObserved",
    "PriceableSubject",
    "PricingError",
    "ResolutionPolicy",
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
