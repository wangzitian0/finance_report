"""``PriceObserved`` — the domain event pricing publishes when a new observation lands.

Consumers (e.g. a future durable rollup, or cross-package notification) react
to this rather than polling. Per boundary ruling 4, ``extraction`` is a
*producer* into pricing (a statement-extracted unit price arrives as an
id-referenced observation), not a subscriber of this event; this event is
pricing's own outbound fact, published via the platform outbox (mechanism C —
no compile-time edge, no shared transaction).

``PriceObserved`` is a :class:`~src.platform.base.event.DomainEvent`: it
carries the universal ``event_type``/``occurred_at`` and exposes its fields
via :meth:`payload` so the outbox can persist it as JSON and the relay can
rehydrate it for subscribers — the same shape as ``counter.Incremented``, the
one other producer in this codebase. This is the one place pricing depends
(downward) on ``platform`` for the event base.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from src.platform.base import DomainEvent
from src.pricing.base.observation import ObservationSource
from src.pricing.base.subject import PriceableSubject

#: The stable, namespaced routing key the bus/relay dispatch this event on.
EVENT_TYPE = "pricing.PriceObserved"


@dataclass(frozen=True)
class PriceObserved(DomainEvent):
    """A fact: a new ``PriceObservation`` (``observation_id``) was recorded."""

    observation_id: UUID
    subject: PriceableSubject
    as_of: date
    source: ObservationSource

    @classmethod
    def create(
        cls,
        *,
        observation_id: UUID,
        subject: PriceableSubject,
        as_of: date,
        source: ObservationSource,
        occurred_at: datetime,
    ) -> PriceObserved:
        """Build a ``PriceObserved`` with the fixed ``pricing.PriceObserved`` type."""
        return cls(
            event_type=EVENT_TYPE,
            occurred_at=occurred_at,
            observation_id=observation_id,
            subject=subject,
            as_of=as_of,
            source=source,
        )

    def payload(self) -> dict:
        """JSON body persisted to the outbox: observation_id, subject, as_of, source."""
        return {
            "aggregate_id": str(self.observation_id),
            "observation_id": str(self.observation_id),
            "subject_kind": self.subject.kind.value,
            "subject_key": self.subject.key,
            "as_of": self.as_of.isoformat(),
            "source": self.source.value,
        }
