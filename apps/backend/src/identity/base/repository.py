"""``UserRepository`` — the identity persistence *port* (a typing.Protocol).

The domain services (``register``/``login``/``get_current_user_id``) depend on
this Protocol, not on a concrete store, so the auth verbs are expressible against
an abstraction (mechanism B, dependency inversion). The SQL adapter lives in
``extension/sql.py``; the session/ORM never leaks above this line.

The port speaks the ``User`` aggregate through a **structural** ``UserLike``
Protocol (``id``/``email``/``hashed_password``/``name``), so the pure core gets a
meaningful boundary type without importing the ORM ``User`` (the concrete ORM
model in ``extension/sql.py`` satisfies ``UserLike`` structurally). The value
objects (``RegisterRequest``/``AuthResponse``/…) stay ORM-free.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class UserLike(Protocol):
    """The structural shape of the ``User`` aggregate the port reads/writes.

    A duck-typed view of the persisted user: the ORM ``User`` in
    ``extension/sql.py`` satisfies it structurally, so ``base`` types the port
    boundary meaningfully without importing the ORM model.
    """

    id: UUID
    email: str
    hashed_password: str
    name: str | None


class UserRepository(Protocol):
    """Identity persistence port: user existence, lookup-by-email, and creation.

    Implementations are async and back onto an ``AsyncSession`` (see
    ``extension/sql.py``); the pure core depends only on this abstraction.
    """

    async def exists(self, user_id: UUID) -> bool:
        """Return True iff a user row with ``user_id`` exists."""
        ...

    async def get_by_normalized_email(self, normalized_email: str) -> UserLike | None:
        """Return the ``UserLike`` aggregate whose normalized email matches, or None."""
        ...

    async def add(self, user: UserLike) -> None:
        """Stage a new ``UserLike`` aggregate for persistence (caller owns the commit)."""
        ...
