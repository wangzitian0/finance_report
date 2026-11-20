"""``platform`` — transactional outbox EventBus, rate limiting, and shared domain errors."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from src.platform.base import (
    BadGatewayError,
    BaseAppException,
    ConflictError,
    ContentTooLargeError,
    DomainError,
    DomainEvent,
    EventBus,
    ForbiddenError,
    GatewayTimeoutError,
    InternalServiceError,
    Outbox,
    OutboxRepository,
    PreconditionFailedError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    SubscriberRegistry,
    TooManyRequestsError,
    UnauthorizedError,
    ValidationFailedError,
    require_base_currency,
    validate_internal_action_href,
)

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly so importing the package registers the mappers on Base.metadata.
from src.platform.orm.app_config import BASE_CURRENCY_KEY, AppConfig
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin

_EXTENSION_EXPORTS = {
    "OutboxEventBus",
    "OutboxRelay",
    "RateLimitConfig",
    "RateLimiter",
    "RateLimitState",
    "RecordingEventBus",
    "STATUS_FAILED",
    "get_client_ip",
    "get_owned_or_raise",
    "paginate",
}

__all__ = [
    "AppConfig",
    "BASE_CURRENCY_KEY",
    "BadGatewayError",
    "BaseAppException",
    "ConflictError",
    "ContentTooLargeError",
    "DomainError",
    "DomainEvent",
    "EventBus",
    "ForbiddenError",
    "GatewayTimeoutError",
    "InternalServiceError",
    "Outbox",
    "OutboxEventBus",
    "OutboxRelay",
    "OutboxRepository",
    "PreconditionFailedError",
    "RateLimitConfig",
    "RateLimitState",
    "RateLimiter",
    "RecordingEventBus",
    "ResourceNotFoundError",
    "STATUS_FAILED",
    "ServiceUnavailableError",
    "SubscriberRegistry",
    "TimestampMixin",
    "TooManyRequestsError",
    "UUIDMixin",
    "UnauthorizedError",
    "UserOwnedMixin",
    "ValidationFailedError",
    "get_client_ip",
    "get_owned_or_raise",
    "paginate",
    "require_base_currency",
    "validate_internal_action_href",
]


def __getattr__(name: str) -> object:
    """Resolve extension exports lazily so base DTOs stay cycle-free."""
    if name not in _EXTENSION_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("src.platform.extension"), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from src.platform.extension import (
        OutboxEventBus,
        OutboxRelay,
        RateLimitConfig,
        RateLimiter,
        RateLimitState,
        RecordingEventBus,
        STATUS_FAILED,
        get_client_ip,
        get_owned_or_raise,
        paginate,
    )
