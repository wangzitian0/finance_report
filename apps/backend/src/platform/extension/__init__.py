"""``platform.extension`` — the impure edges: ORM, session, and the bus adapters.

Depends on ``src.database`` (the shared ORM Base/session) and on the package's own
``base`` ports. This is where the package reaches I/O: the shared :class:`Outbox`
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
    Outbox,
    SqlOutboxRepository,
)
from src.platform.extension.workflow_event_builders import StatementEventSource
from src.platform.extension.workflow_events import (
    get_workflow_status,
    list_workflow_events_response,
    register_readiness_provider,
    register_statement_reader,
    register_uploaded_document_readers,
    update_workflow_event_status,
)

__all__ = [
    "BaseAppException",
    "Outbox",
    "OutboxEventBus",
    "OutboxRelay",
    "RateLimitConfig",
    "RateLimitState",
    "RateLimiter",
    "RecordingEventBus",
    "STATUS_PENDING",
    "STATUS_PUBLISHED",
    "SqlOutboxRepository",
    "StatementEventSource",
    "get_owned_or_404",
    "get_workflow_status",
    "list_workflow_events_response",
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
    "register_readiness_provider",
    "register_statement_reader",
    "register_uploaded_document_readers",
    "update_workflow_event_status",
]
