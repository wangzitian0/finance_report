"""``PriceObserved`` — the domain event announcing a price observation fact.

Two producers publish it (both via the platform outbox, mechanism C — no
compile-time edge, no shared transaction):

- **pricing itself** (``record_manual_valuation``/``record_override``): the
  observation already lives in pricing's store; the event is pricing's own
  outbound fact for downstream reactors (e.g. a future durable rollup).
- **extraction** (boundary ruling 4, #1610 / #1642): a statement-extracted
  unit price stays in ``extraction`` (document-fact, provenance chain,
  re-parse lifecycle) and is announced with ``source=STATEMENT`` and
  ``observation_id`` = the extraction fact id. Pricing's ingest subscriber
  (``extension/ingest.py``) consumes it into an id-referenced observation
  copy — extraction never subscribes to this event, and pricing never reads
  extraction's tables.

The event therefore carries the full observation value (``value``/``currency``/
``user_id``), not just the id: a consumer must be able to build the copy from
the payload alone, because reaching back into the producer's tables would
re-create the compile-time/runtime coupling the event exists to remove.
``observation_id`` doubles as the natural dedup key for at-least-once delivery.

``PriceObserved`` is a :class:`~src.platform.base.event.DomainEvent`: it
carries the universal ``event_type``/``occurred_at`` and exposes its fields
via :meth:`payload` so the outbox can persist it as JSON and the relay can
rehydrate it for subscribers — the same shape as ``counter.Incremented``.
This is the one place pricing depends (downward) on ``platform`` for the
event base.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from src.platform.base import DomainEvent
from src.pricing.base.observation import ObservationSource
from src.pricing.base.subject import PriceableSubject

#: The stable, namespaced routing key the bus/relay dispatch this event on.
EVENT_TYPE = "pricing.PriceObserved"


@dataclass(frozen=True)
class PriceObserved(DomainEvent):
    """A fact: a price observation (``observation_id``) was recorded.

    ``observation_id`` is the producer-side fact id — a pricing store id when
    pricing publishes, the extraction fact id when extraction publishes — and
    is the event's natural dedup key. ``value`` is a ``Decimal`` (never
    ``float``, the standing red line) in ``currency``; ``user_id`` scopes
    user-owned observations (``None`` for global sources).
    """

    observation_id: UUID
    subject: PriceableSubject
    as_of: date
    source: ObservationSource
    value: Decimal
    currency: str | None = None
    user_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        observation_id: UUID,
        subject: PriceableSubject,
        as_of: date,
        source: ObservationSource,
        value: Decimal,
        currency: str | None = None,
        user_id: UUID | None = None,
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
            value=value,
            currency=currency,
            user_id=user_id,
        )

    def payload(self) -> dict:
        """JSON body persisted to the outbox: the id-referenced observation copy."""
        return {
            "aggregate_id": str(self.observation_id),
            "observation_id": str(self.observation_id),
            "subject_kind": self.subject.kind.value,
            "subject_key": self.subject.key,
            "as_of": self.as_of.isoformat(),
            "source": self.source.value,
            "value": str(self.value),
            "currency": self.currency,
            "user_id": str(self.user_id) if self.user_id is not None else None,
        }
