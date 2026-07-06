"""``PriceObserved`` — the domain event pricing publishes when a new observation lands.

Consumers (e.g. a future durable rollup, or cross-package notification) react
to this rather than polling. Per boundary ruling 4, ``extraction`` is a
*producer* into pricing (a statement-extracted unit price arrives as an
id-referenced observation), not a subscriber of this event; this event is
pricing's own outbound fact, published via the platform outbox (mechanism C —
no compile-time edge, no shared transaction).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from src.pricing.base.observation import ObservationSource
from src.pricing.base.subject import PriceableSubject


@dataclass(frozen=True, slots=True)
class PriceObserved:
    """A new ``PriceObservation`` was recorded."""

    observation_id: UUID
    subject: PriceableSubject
    as_of: date
    source: ObservationSource
