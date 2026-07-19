"""``platform.extension`` — the impure edges: ORM, session, and the bus adapters.

Depends on ``src.database`` (the shared ORM Base/session) and on the package's own
``base`` ports. This is where the package reaches I/O: the shared ``OutboxRecord``
table + its :class:`SqlOutboxRepository` adapter (``sql.py``), the
:class:`OutboxEventBus`/:class:`RecordingEventBus` bus adapters (``bus.py``), the
:class:`OutboxRelay` post-commit dispatcher (``relay.py``), the cross-cutting
request :class:`RateLimiter` middleware (``rate_limit.py``), the shared HTTP
error vocabulary (``http_errors.py``: the ``raise_*`` helpers +
:class:`BaseAppException`), and the shared owned-row/pagination query helpers
(``queries.py``). The ``base`` layer stays pure behind the ports these adapters
satisfy.
"""

from __future__ import annotations

from src.platform.extension.api import PingStateResponse, router as platform_system_router
from src.platform.extension.bus import OutboxEventBus, RecordingEventBus
from src.platform.extension.http_errors import (
    BaseAppException,
    raise_bad_request,
    raise_conflict,
    raise_gateway_timeout,
    raise_internal_error,
    raise_not_found,
    raise_service_unavailable,
    raise_too_large,
    raise_too_many_requests,
    raise_unauthorized,
)
from src.platform.extension.queries import get_owned_or_404, paginate
from src.platform.extension.rate_limit import (
    RateLimitConfig,
    RateLimiter,
    RateLimitState,
)
from src.platform.extension.relay import OutboxRelay
from src.platform.extension.sql import (
    STATUS_PENDING,
    STATUS_PUBLISHED,
    SqlOutboxRepository,
)

__all__ = [
    "BaseAppException",
    "OutboxEventBus",
    "OutboxRelay",
    "PingStateResponse",
    "RateLimitConfig",
    "RateLimitState",
    "RateLimiter",
    "RecordingEventBus",
    "STATUS_PENDING",
    "STATUS_PUBLISHED",
    "SqlOutboxRepository",
    "get_owned_or_404",
    "paginate",
    "raise_bad_request",
    "raise_conflict",
    "raise_gateway_timeout",
    "raise_internal_error",
    "raise_not_found",
    "raise_service_unavailable",
    "raise_too_large",
    "raise_too_many_requests",
    "raise_unauthorized",
    "platform_system_router",
]
