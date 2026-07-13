"""Identity transport boundary — the ``/auth`` and ``/users`` routers.

The HTTP edge of the identity package: the auth router (with its ``register`` /
``login`` / ``get_me`` domain operations) and the legacy user-management router.
``api`` is the only role that wires FastAPI transport to the domain services.
"""

from __future__ import annotations

from src.identity.extension.api.auth import (
    get_me,
    login,
    register,
    router as auth_router,
)
from src.identity.extension.api.users import (
    register_in_flight_parse_checker,
    router as users_router,
)

__all__ = [
    "auth_router",
    "get_me",
    "login",
    "register",
    "register_in_flight_parse_checker",
    "users_router",
]
