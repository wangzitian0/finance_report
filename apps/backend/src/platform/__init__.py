"""``platform`` — transactional outbox EventBus, rate limiting, and shared middleware."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from src.platform.base import (
    DomainEvent,
    EventBus,
    Outbox,
    OutboxRepository,
    SubscriberRegistry,
    validate_internal_action_href,
)

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly so importing the package registers the mappers on Base.metadata.
from src.platform.orm.app_config import BASE_CURRENCY_KEY, AppConfig
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin
from src.platform.orm.ping_state import PingState

_EXTENSION_EXPORTS = {
    "BaseAppException",
    "OutboxEventBus",
    "OutboxRelay",
    "PingStateResponse",
    "RateLimitConfig",
    "RateLimiter",
    "RateLimitState",
    "RecordingEventBus",
    "get_client_ip",
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
}

__all__ = [
    "AppConfig",
    "BASE_CURRENCY_KEY",
    "BaseAppException",
    "DomainEvent",
    "EventBus",
    "Outbox",
    "OutboxEventBus",
    "OutboxRelay",
    "OutboxRepository",
    "PingState",
    "PingStateResponse",
    "RateLimitConfig",
    "RateLimitState",
    "RateLimiter",
    "RecordingEventBus",
    "SubscriberRegistry",
    "TimestampMixin",
    "UUIDMixin",
    "UserOwnedMixin",
    "get_client_ip",
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
        BaseAppException,
        OutboxEventBus,
        OutboxRelay,
        PingStateResponse,
        RateLimitConfig,
        RateLimiter,
        RateLimitState,
        RecordingEventBus,
        get_client_ip,
        get_owned_or_404,
        paginate,
        platform_system_router,
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
