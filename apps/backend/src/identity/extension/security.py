"""Identity security domain services: JWT tokens + bcrypt password hashing.

The impure crypto edges of the identity package (KIND_LAYER places domain
services in ``extension``): ``create_access_token``/``decode_access_token`` (JWT,
signed with the configured ``SECRET_KEY``) and ``hash_password``/``verify_password``
(bcrypt with per-password salt). These were the pre-migration ``src/security.py``
JWT helpers + the bcrypt helpers from ``src/routers/auth.py``, consolidated into
the package's single home.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

# Imported by its bare published root (the package-model idiom, mirroring
# ``observability``): ``src.config`` is a kernel package whose ``settings`` is read
# via ``src.config.settings`` so a monkeypatched ``settings`` is always reflected
# and the cross-domain gate sees only the bare-root import.
import src.config
from src.logger import get_logger

logger = get_logger(__name__)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a new JWT access token."""
    settings = src.config.settings
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token."""
    settings = src.config.settings
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token expired")
        return None
    except jwt.PyJWTError as exc:
        logger.warning(
            "JWT decode failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt (per-password salt)."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash (constant-time comparison)."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
