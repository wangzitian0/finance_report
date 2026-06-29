"""``identity.base`` — the pure, self-contained core (value objects + the port).

No I/O and no concrete cross-package wiring: it never imports this package's own
``extension`` layer or the ORM. It holds the auth/AI-feedback value objects (the
published wire language) and the ``UserRepository`` *port* (a ``Protocol``) that
the ``extension`` adapter satisfies. The ``User`` aggregate / ``AiFeedback`` entity
ORM models live with the SQL adapter in ``extension`` (like ``counter``'s
``CounterTally``), so ``base`` stays free of SQLAlchemy.
"""

from __future__ import annotations

from src.identity.base.repository import UserRepository
from src.identity.base.types import (
    AUTH_COOKIE_NAME,
    AiFeedbackRequest,
    AiFeedbackResponse,
    AiSuggestionListResponse,
    AiSuggestionResponse,
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
    "UserRepository",
    "normalize_email",
]
