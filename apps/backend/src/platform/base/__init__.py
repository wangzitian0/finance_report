"""``platform.base`` — the pure core: the event record + the bus/repo ports.

No I/O, no ORM, no session: this layer never imports the package's own
``extension`` layer (the gate enforces it). It holds :class:`DomainEvent` (the
frozen event record), the :class:`EventBus` *port* + :class:`SubscriberRegistry`
(pure routing state), and the :class:`OutboxRepository` *port* — the abstract
contracts the concrete ``extension`` adapters satisfy (dependency inversion).
Consumer packages (e.g. ``counter``) depend on these ports, never on the
adapters.
"""

from __future__ import annotations

from src.platform.base.bus import EventBus, EventHandler, SubscriberRegistry
from src.platform.base.event import DomainEvent
from src.platform.base.outbox import Outbox, OutboxRepository, OutboxRow

__all__ = [
    "DomainEvent",
    "EventBus",
    "EventHandler",
    "Outbox",
    "OutboxRepository",
    "OutboxRow",
    "SubscriberRegistry",
]
