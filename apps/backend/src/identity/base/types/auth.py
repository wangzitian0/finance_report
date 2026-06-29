"""Identity request/response value objects (the package's published wire language).

These are pure Pydantic value objects — no ORM, no session, no transport. They are
the identity package's self-owned SSOT vocabulary for the registration/login
boundary (``RegisterRequest``/``LoginRequest``/``AuthResponse``), plus
``AUTH_COOKIE_NAME`` (the browser session-cookie key) and ``normalize_email`` (the
canonical identity key derivation). They know nothing about persistence, exactly
like ``counter``'s ``CounterKey``/``Count``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

#: The HttpOnly browser session-cookie name carrying the JWT access token.
AUTH_COOKIE_NAME = "finance_access_token"


def normalize_email(email: str) -> str:
    """Return the canonical identity key used for registration and login.

    Trim surrounding whitespace and Unicode case-fold, so case/whitespace variants
    of an address resolve to one identity (the DB's unique normalized-email index
    enforces the same canonical key).
    """
    return email.strip().casefold()


class RegisterRequest(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]
    name: str | None = None


class LoginRequest(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """Schema for auth response - returns user info and JWT token."""

    id: UUID
    email: str
    name: str | None = None
    created_at: datetime
    access_token: str
    token_type: str = "bearer"

    model_config = ConfigDict(from_attributes=True)
