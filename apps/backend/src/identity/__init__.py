"""``identity`` — users, authentication, and AI-feedback (core domain package).

The vertical identity slice: the ``User`` aggregate root (email unique
case-insensitively), its ``AiFeedback`` child entity, the auth value objects, and
the domain services that register/login users and resolve request-scoped identity
from a JWT. Layers (see common/meta/migration-standard.md): ``base`` (pure value
objects + the ``UserRepository`` port) and ``extension`` (the ORM adapter, JWT +
bcrypt security, the auth rate limiters, observability binding, and the ``/auth``
+ ``/users`` transport). The published language below (``__all__``) must equal
``contract.interface``.

The ORM ``User``/``AiFeedback`` models live with the SQL adapter in ``extension``
(like ``counter``'s ``CounterTally``); they are published here because consumers
(routers, tests, factories) reference the aggregate directly.

Symbols are exposed **lazily** (PEP 562 ``__getattr__``): the published names
resolve on first access, so importing the package — or one of its submodules for
its side effect, e.g. ``import src.identity.extension.sql`` to register the ORM
onto ``Base.metadata`` — does NOT eagerly pull the FastAPI transport layer. This
keeps the package importable in the lightweight (FastAPI-free) tooling/coverage
environment, exactly as a model-registration import must be.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Map each published name to the submodule that defines it. Resolved lazily so the
# FastAPI-dependent transport (auth dep + routers) is only imported on demand.
_BASE_EXPORTS = {
    "AUTH_COOKIE_NAME",
    "AiFeedbackRequest",
    "AiFeedbackResponse",
    "AiSuggestionListResponse",
    "AiSuggestionResponse",
    "AuthResponse",
    "LoginRequest",
    "RegisterRequest",
    "UserRepository",
    "normalize_email",
}
_EXTENSION_EXPORTS = {
    "AiFeedback",
    "DEFAULT_TEST_EMAIL_PATTERN",
    "PurgeReport",
    "User",
    "auth_rate_limiter",
    "auth_router",
    "bind_authenticated_user_context",
    "create_access_token",
    "decode_access_token",
    "get_current_user_id",
    "get_me",
    "hash_password",
    "is_safe_purge_environment",
    "login",
    "oauth2_scheme",
    "purge_test_accounts",
    "register",
    "register_in_flight_parse_checker",
    "register_rate_limiter",
    "users_router",
    "verify_password",
}

__all__ = [
    "AUTH_COOKIE_NAME",
    "AiFeedback",
    "AiFeedbackRequest",
    "AiFeedbackResponse",
    "AiSuggestionListResponse",
    "AiSuggestionResponse",
    "AuthResponse",
    "DEFAULT_TEST_EMAIL_PATTERN",
    "LoginRequest",
    "PurgeReport",
    "RegisterRequest",
    "User",
    "UserRepository",
    "auth_rate_limiter",
    "auth_router",
    "bind_authenticated_user_context",
    "create_access_token",
    "decode_access_token",
    "get_current_user_id",
    "get_me",
    "hash_password",
    "is_safe_purge_environment",
    "login",
    "normalize_email",
    "oauth2_scheme",
    "purge_test_accounts",
    "register",
    "register_in_flight_parse_checker",
    "register_rate_limiter",
    "users_router",
    "verify_password",
]


def __getattr__(name: str) -> object:
    """Lazily resolve a published symbol from its owning layer (PEP 562)."""
    if name in _BASE_EXPORTS:
        from src.identity import base

        return getattr(base, name)
    if name in _EXTENSION_EXPORTS:
        from src.identity import extension

        return getattr(extension, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover - static type-checker view of the lazy exports
    from src.identity.base import (
        AUTH_COOKIE_NAME,
        AiFeedbackRequest,
        AiFeedbackResponse,
        AiSuggestionListResponse,
        AiSuggestionResponse,
        AuthResponse,
        LoginRequest,
        RegisterRequest,
        UserRepository,
        normalize_email,
    )
    from src.identity.extension import (
        DEFAULT_TEST_EMAIL_PATTERN,
        AiFeedback,
        PurgeReport,
        User,
        auth_rate_limiter,
        auth_router,
        bind_authenticated_user_context,
        create_access_token,
        decode_access_token,
        get_current_user_id,
        get_me,
        hash_password,
        is_safe_purge_environment,
        login,
        oauth2_scheme,
        purge_test_accounts,
        register,
        register_in_flight_parse_checker,
        register_rate_limiter,
        users_router,
        verify_password,
    )
