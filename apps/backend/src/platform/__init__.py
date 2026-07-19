"""``platform`` — the backend implementation of the ``platform`` package.

This is ``PackageContract.implementations["be"]`` for the ``platform`` package
(the technical substrate logically labelled *middleware*); the authoritative spec
(ubiquitous language, contract, roadmap) lives in ``common/platform/``
(``readme.md`` + ``contract.py``). See ``common/meta/readme.md`` for the package
model.

``platform`` is the meta layer's first *runtime* capability: a domain
**EventBus implemented via the transactional outbox pattern**. A producer
``publish``es a :class:`DomainEvent` through an :class:`OutboxEventBus`, which
INSERTs it into the shared ``outbox`` table *in the producer's own DB
transaction* — so the event commits atomically with the domain state change. A
separate :class:`OutboxRelay` later reads committed ``pending`` rows and
dispatches them to subscribed handlers (at-least-once; handlers must be
idempotent), making dispatch inherently post-commit.

Files converge by layer (see common/meta/migration-standard.md): ``base`` (the
:class:`DomainEvent` record + the :class:`EventBus`/:class:`OutboxRepository`
*ports* + :class:`SubscriberRegistry`) and ``extension`` (the
:class:`OutboxEventBus`/:class:`RecordingEventBus` bus adapters, the
:class:`OutboxRelay`, the SQL ``OutboxRecord`` table + adapter — the only role
that touches the ORM — and the cross-cutting request :class:`RateLimiter`
middleware service plus its app-wide ``api_rate_limiter`` instance). The names
re-exported below are the *entire* public surface (``__all__`` must equal
``contract.interface``); the concrete ``Sql*`` adapter is internal (reached only
through its port).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from src.platform.base import (
    DomainEvent,
    EventBus,
    Outbox,
    OutboxRepository,
    SubscriberRegistry,
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
