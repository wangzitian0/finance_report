"""The concrete event-bus adapters (the ``extension`` half of the bus).

These satisfy the :class:`~src.platform.base.bus.EventBus` port (dependency
inversion, mechanism B): :class:`OutboxEventBus` is the production adapter that
writes through the shared outbox table; :class:`RecordingEventBus` is an in-memory
fake for unit tests. Both depend on the pure ``base`` layer (the port, the
registry, the event record) and, for the production adapter, on the SQL outbox
adapter in ``extension/sql.py``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.base.bus import EventHandler, SubscriberRegistry
from src.platform.base.event import DomainEvent
from src.platform.extension.sql import SqlOutboxRepository


class OutboxEventBus:
    """The production bus: ``publish`` writes the event into the shared outbox.

    Constructed from an :class:`~sqlalchemy.ext.asyncio.AsyncSession`, so
    ``publish`` enqueues the event *in that session's transaction* — atomic with
    whatever domain write the caller is performing. No dispatch happens on
    publish; the :class:`~src.platform.extension.relay.OutboxRelay` drains
    committed pending rows out-of-band. ``source_pkg`` tags every row with the
    producing package so the relay/operators can attribute events.
    """

    def __init__(
        self, session: AsyncSession, *, source_pkg: str, registry: SubscriberRegistry | None = None
    ) -> None:
        self._repo = SqlOutboxRepository(session)
        self._source_pkg = source_pkg
        self._registry = registry or SubscriberRegistry()

    def publish(self, event: DomainEvent) -> None:
        """INSERT ``event`` into the outbox in the caller's transaction."""
        payload = event.payload()
        self._repo.enqueue(
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            source_pkg=self._source_pkg,
            payload=payload,
            aggregate_id=payload.get("aggregate_id"),
        )

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler on the shared registry (consumed by the relay)."""
        self._registry.subscribe(event_type, handler)


class RecordingEventBus:
    """In-memory test fake: ``publish`` appends to :attr:`published`.

    Lets a unit test assert "exactly these events were published" without a
    database or a relay. ``subscribe`` records handlers too, so a test can verify
    registration. It is NOT transactional — production atomicity is the outbox
    adapter's job; this fake exists purely to observe publish calls.
    """

    def __init__(self, registry: SubscriberRegistry | None = None) -> None:
        self.published: list[DomainEvent] = []
        self._registry = registry or SubscriberRegistry()

    def publish(self, event: DomainEvent) -> None:
        """Record ``event`` in memory (no persistence, no dispatch)."""
        self.published.append(event)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Record ``handler`` on the registry for ``event_type``."""
        self._registry.subscribe(event_type, handler)
