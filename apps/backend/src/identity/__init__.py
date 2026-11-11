"""``identity`` — users, authentication, and AI-feedback domain package."""

from __future__ import annotations

from typing import TYPE_CHECKING

_BASE_EXPORTS = {
    "AUTH_COOKIE_NAME",
    "AiFeedbackRequest",
    "AiFeedbackResponse",
    "AiSuggestionListResponse",
    "AiSuggestionResponse",
    "AuthResponse",
    "LoginRequest",
    "RegisterRequest",
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "UserBase",
    "UserRepository",
    "UserResponse",
    "UserUpdate",
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
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "UserBase",
    "UserRepository",
    "UserResponse",
    "UserUpdate",
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
        UserAiSettingsResponse,
        UserAiSettingsUpdate,
        UserBase,
        UserRepository,
        UserResponse,
        UserUpdate,
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
