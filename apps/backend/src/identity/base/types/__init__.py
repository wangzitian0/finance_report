"""Identity value objects (the package's published wire language).

The pure request/response types and the canonical-key helpers — no ORM, no
session, no transport. These are the identity package's self-owned SSOT
vocabulary for the auth boundary and the AI-feedback entity.
"""

from __future__ import annotations

from src.identity.base.types.ai_feedback import (
    AiFeedbackRequest,
    AiFeedbackResponse,
    AiSuggestionListResponse,
    AiSuggestionResponse,
)
from src.identity.base.types.auth import (
    AUTH_COOKIE_NAME,
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    normalize_email,
)

__all__ = [
    "AUTH_COOKIE_NAME",
    "AiFeedbackRequest",
    "AiFeedbackResponse",
    "AiSuggestionListResponse",
    "AiSuggestionResponse",
    "AuthResponse",
    "LoginRequest",
    "RegisterRequest",
    "normalize_email",
]
