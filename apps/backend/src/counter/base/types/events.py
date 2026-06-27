"""``Incremented`` — the counter domain event (published language).

A package's *events* are part of its published interface: other contexts react
to ``Incremented`` (e.g. insight-report generation) without importing the
counter store or ops. The event is an immutable record of a fact that already
happened — a per-(user, key) tally was bumped to ``count`` at ``occurred_at``.

``Incremented`` is a :class:`~src.platform.base.event.DomainEvent`: it carries
the universal ``event_type`` (``"counter.Incremented"``) and ``occurred_at``, and
exposes its fields via :meth:`payload` so the platform outbox can persist it as
JSON and the relay can rehydrate it for subscribers. This is the one place the
counter package depends (downward) on the ``platform`` package — the event base.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.counter.base.types.key import CounterKey
from src.platform.base import DomainEvent

#: The stable, namespaced routing key the bus/relay dispatch this event on.
EVENT_TYPE = "counter.Incremented"


@dataclass(frozen=True)
class Incremented(DomainEvent):
    """A fact: ``user_id``'s tally for ``key`` reached ``count`` at ``occurred_at``."""

    user_id: UUID
    key: CounterKey
    count: int

    @classmethod
    def create(cls, *, user_id: UUID, key: CounterKey, count: int, at: datetime) -> Incremented:
        """Build an ``Incremented`` with the fixed ``counter.Incremented`` type."""
        return cls(
            event_type=EVENT_TYPE,
            occurred_at=at,
            user_id=user_id,
            key=key,
            count=count,
        )

    def payload(self) -> dict:
        """JSON body persisted to the outbox: user_id, key, count, at."""
        return {
            "aggregate_id": str(self.user_id),
            "user_id": str(self.user_id),
            "key": self.key.value,
            "count": self.count,
            "at": self.occurred_at.isoformat(),
        }
