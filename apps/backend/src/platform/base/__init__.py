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
from src.platform.base.currency import require_base_currency
from src.platform.base.errors import (
    BadGatewayError,
    BaseAppException,
    ConflictError,
    ContentTooLargeError,
    DomainError,
    ForbiddenError,
    GatewayTimeoutError,
    InternalServiceError,
    PreconditionFailedError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
    UnauthorizedError,
    ValidationFailedError,
)
from src.platform.base.event import DomainEvent
from src.platform.base.href import validate_internal_action_href
from src.platform.base.outbox import Outbox, OutboxRepository, OutboxRow

__all__ = [
    "BadGatewayError",
    "BaseAppException",
    "ConflictError",
    "ContentTooLargeError",
    "DomainError",
    "DomainEvent",
    "EventBus",
    "EventHandler",
    "ForbiddenError",
    "GatewayTimeoutError",
    "InternalServiceError",
    "Outbox",
    "OutboxRepository",
    "OutboxRow",
    "PreconditionFailedError",
    "ResourceNotFoundError",
    "ServiceUnavailableError",
    "SubscriberRegistry",
    "TooManyRequestsError",
    "UnauthorizedError",
    "ValidationFailedError",
    "require_base_currency",
    "validate_internal_action_href",
]
