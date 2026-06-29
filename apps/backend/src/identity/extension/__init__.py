"""``identity.extension`` — the impure edges: ORM, crypto, transport, observability.

Depends on ``src.database`` (ORM), the ``platform`` package (rate limiter), the
``observability`` package, and FastAPI transport. This is where the package
reaches across to I/O and other packages; the ``base`` layer stays pure behind the
``UserRepository`` port this layer satisfies.

Symbols are exposed **lazily** (PEP 562 ``__getattr__``) so importing this layer's
ORM module for its registration side effect (``import src.identity.extension.sql``)
does NOT eagerly pull the FastAPI-dependent transport (``api/``) or auth dependency
— keeping ORM registration importable in the FastAPI-free tooling environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Each published name -> the submodule that defines it (the symbol name is the key
# itself). The ``api`` (routers) and ``auth`` (oauth2_scheme/get_current_user_id)
# modules import FastAPI, so they are resolved on demand, not at layer-import time.
_LAZY = {
    "auth_router": "src.identity.extension.api",
    "get_me": "src.identity.extension.api",
    "login": "src.identity.extension.api",
    "register": "src.identity.extension.api",
    "users_router": "src.identity.extension.api",
    "get_current_user_id": "src.identity.extension.auth",
    "oauth2_scheme": "src.identity.extension.auth",
    "bind_authenticated_user_context": "src.identity.extension.observability",
    "auth_rate_limiter": "src.identity.extension.rate_limit",
    "register_rate_limiter": "src.identity.extension.rate_limit",
    "create_access_token": "src.identity.extension.security",
    "decode_access_token": "src.identity.extension.security",
    "hash_password": "src.identity.extension.security",
    "verify_password": "src.identity.extension.security",
    "AiFeedback": "src.identity.extension.sql",
    "SqlUserRepository": "src.identity.extension.sql",
    "User": "src.identity.extension.sql",
}

__all__ = [
    "AiFeedback",
    "SqlUserRepository",
    "User",
    "auth_rate_limiter",
    "auth_router",
    "bind_authenticated_user_context",
    "create_access_token",
    "decode_access_token",
    "get_current_user_id",
    "get_me",
    "hash_password",
    "login",
    "oauth2_scheme",
    "register",
    "register_rate_limiter",
    "users_router",
    "verify_password",
]


def __getattr__(name: str) -> object:
    """Lazily import and return a published extension symbol (PEP 562)."""
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)


if TYPE_CHECKING:  # pragma: no cover - static type-checker view of the lazy exports
    from src.identity.extension.api import (
        auth_router,
        get_me,
        login,
        register,
        users_router,
    )
    from src.identity.extension.auth import get_current_user_id, oauth2_scheme
    from src.identity.extension.observability import bind_authenticated_user_context
    from src.identity.extension.rate_limit import auth_rate_limiter, register_rate_limiter
    from src.identity.extension.security import (
        create_access_token,
        decode_access_token,
        hash_password,
        verify_password,
    )
    from src.identity.extension.sql import AiFeedback, SqlUserRepository, User
