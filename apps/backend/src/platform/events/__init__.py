"""Platform event language — the bus, the relay, and the event base type.

``DomainEvent`` (the frozen event value type), ``EventBus`` (the publish/subscribe
port) with its ``OutboxEventBus`` adapter and ``RecordingEventBus`` fake, the
``SubscriberRegistry`` routing map, and the ``OutboxRelay`` that dispatches
committed rows post-commit.
"""

from __future__ import annotations

from src.platform.events.bus import (
    EventBus,
    EventHandler,
    OutboxEventBus,
    RecordingEventBus,
    SubscriberRegistry,
)
from src.platform.events.event import DomainEvent
from src.platform.events.relay import OutboxRelay

__all__ = [
    "DomainEvent",
    "EventBus",
    "EventHandler",
    "OutboxEventBus",
    "OutboxRelay",
    "RecordingEventBus",
    "SubscriberRegistry",
]
