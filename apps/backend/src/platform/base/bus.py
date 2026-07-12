"""The domain ``EventBus`` *port* + the pure routing state it shares with a relay.

This is the ``base`` (pure) half of the bus — dependency inversion, mechanism B:
the abstract :class:`EventBus` protocol the pure core depends on lives here; its
concrete adapters (:class:`~src.platform.extension.bus.OutboxEventBus`,
:class:`~src.platform.extension.bus.RecordingEventBus`) live in ``extension`` and
depend back on this port. The bus has two halves that meet at the outbox table:

- **publish** (write side) — a producer hands the bus a :class:`DomainEvent`; an
  adapter persists it. The production adapter INSERTs it into the shared outbox
  table *through the caller's session*, so the event commits atomically with the
  domain state change. Dispatch does NOT happen on publish — only enqueue.
- **subscribe** (read side) — a consumer registers a handler for an
  ``event_type``. The :class:`~src.platform.extension.relay.OutboxRelay` reads
  committed pending rows and invokes the matching handlers, so dispatch is
  inherently post-commit. Handlers run at-least-once and MUST be idempotent.

:class:`SubscriberRegistry` holds the ``event_type -> handlers`` map shared by a
bus and its relay. It is **pure routing state** (no transport, no I/O), so it
lives in ``base`` and is reused by both the outbox bus in production and the
recording fake in tests.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from src.platform.base.event import DomainEvent

#: A subscriber: a callable invoked by the relay with a reconstructed event.
#: May be sync or async — a coroutine function's awaitable is awaited by the
#: relay before the row is marked published (a DB-writing consumer, e.g.
#: pricing's statement-price ingest, needs an ``AsyncSession`` inside the
#: handler).
EventHandler = Callable[[DomainEvent], None | Awaitable[None]]


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
