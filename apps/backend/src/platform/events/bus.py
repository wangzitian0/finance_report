"""The domain ``EventBus`` — its Protocol, the outbox adapter, and a test fake.

The bus has two halves that meet at the outbox table:

- **publish** (write side) — a producer hands the bus a :class:`DomainEvent`; the
  bus persists it. :class:`OutboxEventBus` does this by INSERTing into the shared
  outbox table *through the caller's session*, so the event commits atomically
  with the domain state change. Dispatch does NOT happen here — only enqueue.
- **subscribe** (read side) — a consumer registers a handler for an
  ``event_type``. The :class:`OutboxRelay` (``events/relay.py``) reads committed
  pending rows and invokes the matching handlers, so dispatch is inherently
  post-commit. Handlers run at-least-once and MUST be idempotent.

:class:`SubscriberRegistry` holds the ``event_type -> handlers`` map shared by a
bus and its relay. :class:`RecordingEventBus` is an in-memory fake for unit tests
that need to assert "what was published" without a database.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from src.platform.events.event import DomainEvent
from src.platform.store.outbox import OutboxRepository

#: A subscriber: a callable invoked by the relay with a reconstructed event.
EventHandler = Callable[[DomainEvent], None]


class SubscriberRegistry:
    """The ``event_type -> [handler]`` map shared by a bus and its relay.

    ``subscribe`` is additive (many handlers per type, in registration order);
    ``handlers_for`` returns the handlers the relay must invoke for a delivered
    event. The registry holds NO transport — it is pure routing state, so the
    same registry can back the outbox bus in production and a recording fake in
    tests.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register ``handler`` to receive events of ``event_type``."""
        self._handlers[event_type].append(handler)

    def handlers_for(self, event_type: str) -> list[EventHandler]:
        """Handlers registered for ``event_type`` (empty list if none)."""
        return list(self._handlers.get(event_type, ()))


@runtime_checkable
class EventBus(Protocol):
    """The port a producer publishes through and a consumer subscribes to.

    ``publish`` is the write entrypoint: it persists the event for later,
    post-commit dispatch (the outbox adapter writes it into the caller's
    transaction). ``subscribe`` registers a handler; dispatch itself is the
    relay's job, not the bus's, which is what keeps the producer ignorant of the
    consumers.
    """

    def publish(self, event: DomainEvent) -> None:
        """Enqueue ``event`` for at-least-once, post-commit delivery."""
        ...

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register ``handler`` to receive events of ``event_type``."""
        ...


class OutboxEventBus:
    """The production bus: ``publish`` writes the event into the shared outbox.

    Constructed from an :class:`AsyncSession`, so ``publish`` enqueues the event
    *in that session's transaction* — atomic with whatever domain write the
    caller is performing. No dispatch happens on publish; the :class:`OutboxRelay`
    drains committed pending rows out-of-band. ``source_pkg`` tags every row with
    the producing package so the relay/operators can attribute events.
    """

    def __init__(self, session, *, source_pkg: str, registry: SubscriberRegistry | None = None) -> None:
        self._repo = OutboxRepository(session)
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
