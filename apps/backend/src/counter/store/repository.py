"""``CounterRepository`` — the persistence *port* (a typing.Protocol).

Ops depend on this Protocol, not on any concrete store, so the domain verbs are
testable without a database (an in-memory fake satisfies the port). The SQL
adapter lives in ``store/sql.py``; the session/ORM never leaks above this line.

The port speaks raw ``int`` (the storage shape); ops narrow those ints to
:class:`~src.counter.types.count.Count` value objects at the package boundary.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.counter.types.key import CounterKey


class CounterRepository(Protocol):
    """Per-(user, key) tally storage. Implementations must be atomic on ``bump``."""

    def bump(self, user_id: UUID, key: CounterKey) -> int:
        """Atomically increment the (user, key) tally by one; return the new value."""
        ...

    def total(self, key: CounterKey) -> int:
        """Return the GLOBAL tally for ``key`` (sum across all users)."""
        ...

    def for_user(self, user_id: UUID, key: CounterKey) -> int:
        """Return the per-user tally for (``user_id``, ``key``); 0 if none."""
        ...
