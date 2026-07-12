"""``JournalRepository`` — the journal persistence *port* (a typing.Protocol).

The posting domain service (``extension/post.py``) depends on this abstract port,
not on any concrete ``AsyncSession`` store, so the verb is testable without a
database (an in-memory fake satisfies the port). The SQL adapter lives in
``extension/repository.py``; the session/ORM never leaks above this line —
mechanism B (dependency inversion).

The port is **async**: ``create`` / ``post`` / ``void`` are inherently
``AsyncSession`` operations. It speaks the ORM ``JournalEntry`` aggregate (the
storage shape); ``post_entry`` narrows the pure :class:`~src.ledger.base.types.entry.Entry`
to ``lines_data`` dicts at the package boundary.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from src.audit import JournalEntrySourceType
from src.ledger.orm.journal import JournalEntry


class JournalRepository(Protocol):
    """Journal write port: create draft / post / void, returning ORM aggregates."""

    async def create(
        self,
        *,
        user_id: UUID,
        entry_date: date,
        memo: str,
        lines_data: list[dict],
        source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
        source_id: UUID | None = None,
    ) -> JournalEntry:
        """Persist a balanced draft entry (validates balance/fx/ownership)."""
        ...

    async def post(self, entry_id: UUID, user_id: UUID) -> JournalEntry:
        """Transition a draft entry to posted (re-validates posting invariants)."""
        ...

    async def void(self, entry_id: UUID, reason: str, user_id: UUID) -> JournalEntry:
        """Void a posted entry via an immutable reversal chain."""
        ...
