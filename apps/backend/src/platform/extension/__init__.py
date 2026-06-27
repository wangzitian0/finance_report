"""``platform.extension`` — the impure edges: ORM, session, and the bus adapters.

Depends on ``src.database`` (the shared ORM Base/session) and on the package's own
``base`` ports. This is where the package reaches I/O: the shared :class:`Outbox`
table + its :class:`SqlOutboxRepository` adapter (``sql.py``), the
:class:`OutboxEventBus`/:class:`RecordingEventBus` bus adapters (``bus.py``), the
:class:`OutboxRelay` post-commit dispatcher (``relay.py``), and the cross-cutting
request :class:`RateLimiter` middleware (``rate_limit.py``). The ``base`` layer
stays pure behind the ports these adapters satisfy.
"""

from __future__ import annotations

from src.platform.extension.bus import OutboxEventBus, RecordingEventBus
from src.platform.extension.rate_limit import (
    RateLimitConfig,
    RateLimiter,
    RateLimitState,
    api_rate_limiter,
)
from src.platform.extension.relay import OutboxRelay
from src.platform.extension.sql import (
    STATUS_PENDING,
    STATUS_PUBLISHED,
    Outbox,
    SqlOutboxRepository,
)

__all__ = [
    "STATUS_PENDING",
    "STATUS_PUBLISHED",
    "Outbox",
    "OutboxEventBus",
    "OutboxRelay",
    "RateLimitConfig",
    "RateLimitState",
    "RateLimiter",
    "RecordingEventBus",
    "SqlOutboxRepository",
    "api_rate_limiter",
]
