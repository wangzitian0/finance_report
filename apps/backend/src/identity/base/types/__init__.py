"""Identity value objects (the package's published wire language).

The pure request/response types and the canonical-key helpers — no ORM, no
session, no transport. These are the identity package's self-owned SSOT
vocabulary for the auth boundary and user settings.
"""

from __future__ import annotations

from src.identity.base.types.auth import (
    AUTH_COOKIE_NAME,
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    normalize_email,
)
from src.identity.base.types.user import (
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
)

__all__ = [
    "AUTH_COOKIE_NAME",
    "AuthResponse",
    "LoginRequest",
    "RegisterRequest",
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "normalize_email",
]
