"""``platform`` — the backend implementation of the ``platform`` package.

This is ``PackageContract.implementations["be"]`` for the ``platform`` package;
the authoritative spec (ubiquitous language, contract, roadmap) lives in
``common/platform/`` (``readme.md`` + ``contract.py``). See
``common/governance/readme.md`` for the package model.

``platform`` is the meta layer's first *runtime* capability: a domain
**EventBus implemented via the transactional outbox pattern**. A producer
``publish``es a :class:`DomainEvent` through an :class:`OutboxEventBus`, which
INSERTs it into the shared ``outbox`` table *in the producer's own DB
transaction* — so the event commits atomically with the domain state change. A
separate :class:`OutboxRelay` later reads committed ``pending`` rows and
dispatches them to subscribed handlers (at-least-once; handlers must be
idempotent), making dispatch inherently post-commit.

Files converge by role — ``events`` (``DomainEvent``, the bus, the relay) and
``store`` (the shared ``Outbox`` table + repository). The names re-exported below
are the *entire* public surface (``__all__`` must equal ``contract.interface``).
"""

from __future__ import annotations

from src.platform.events import (
    DomainEvent,
    EventBus,
    OutboxEventBus,
    OutboxRelay,
    RecordingEventBus,
    SubscriberRegistry,
)
from src.platform.store import Outbox, OutboxRepository

__all__ = [
    "DomainEvent",
    "EventBus",
    "Outbox",
    "OutboxEventBus",
    "OutboxRelay",
    "OutboxRepository",
    "RecordingEventBus",
    "SubscriberRegistry",
]
