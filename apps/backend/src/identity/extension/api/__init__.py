"""Identity transport boundary — the ``/auth`` router.

The HTTP edge of the identity package: the auth router (with its ``register`` /
``login`` / ``get_me`` domain operations).
``api`` is the only role that wires FastAPI transport to the domain services.
"""

from __future__ import annotations

from src.identity.extension.api.auth import (
    get_me,
    login,
    register,
    router as auth_router,
)

__all__ = [
    "auth_router",
    "get_me",
    "login",
    "register",
]
