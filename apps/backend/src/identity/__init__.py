"""``identity`` — users and authentication domain package."""

from __future__ import annotations

from typing import TYPE_CHECKING

_BASE_EXPORTS = {
    "AUTH_COOKIE_NAME",
    "AuthResponse",
    "BaseCurrencyResponse",
    "BaseCurrencyUpdate",
    "LoginRequest",
    "RegisterRequest",
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "UserRepository",
    "normalize_email",
}
_EXTENSION_EXPORTS = {
    "DEFAULT_TEST_EMAIL_PATTERN",
    "PERSISTENT_TEST_EMAILS",
    "PurgeReport",
    "User",
    "auth_rate_limiter",
    "auth_router",
    "bind_authenticated_user_context",
    "create_access_token",
    "decode_access_token",
    "get_current_user_id",
    "get_me",
    "get_user_ai_overrides",
    "hash_password",
    "is_safe_purge_environment",
    "login",
    "oauth2_scheme",
    "purge_test_accounts",
    "register",
    "register_rate_limiter",
    "register_user",
    "verify_password",
}

__all__ = [
    "AUTH_COOKIE_NAME",
    "AuthResponse",
    "BaseCurrencyResponse",
    "BaseCurrencyUpdate",
    "DEFAULT_TEST_EMAIL_PATTERN",
    "LoginRequest",
    "PERSISTENT_TEST_EMAILS",
    "PurgeReport",
    "RegisterRequest",
    "User",
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "UserRepository",
    "auth_rate_limiter",
    "auth_router",
    "bind_authenticated_user_context",
    "create_access_token",
    "decode_access_token",
    "get_current_user_id",
    "get_me",
    "get_user_ai_overrides",
    "hash_password",
    "is_safe_purge_environment",
    "login",
    "normalize_email",
    "oauth2_scheme",
    "purge_test_accounts",
    "register",
    "register_rate_limiter",
    "register_user",
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
        AuthResponse,
        BaseCurrencyResponse,
        BaseCurrencyUpdate,
        LoginRequest,
        RegisterRequest,
        UserAiSettingsResponse,
        UserAiSettingsUpdate,
        UserRepository,
        normalize_email,
    )
    from src.identity.extension import (
        DEFAULT_TEST_EMAIL_PATTERN,
        PERSISTENT_TEST_EMAILS,
        PurgeReport,
        User,
        auth_rate_limiter,
        auth_router,
        bind_authenticated_user_context,
        create_access_token,
        decode_access_token,
        get_current_user_id,
        get_me,
        get_user_ai_overrides,
        hash_password,
        is_safe_purge_environment,
        login,
        oauth2_scheme,
        purge_test_accounts,
        register,
        register_rate_limiter,
        register_user,
        verify_password,
    )
