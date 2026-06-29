"""``ledger.extension`` — the impure edges: the posting service + the SQL adapter.

Depends on ``src.database``-backed ORM models and an ``AsyncSession``. This is
where the package reaches I/O and persistence; the ``base`` layer stays pure behind
the :class:`~src.ledger.base.repository.JournalRepository` port this layer satisfies
(``SqlJournalRepository``). ``post_entry`` is the typed posting verb.
"""

from __future__ import annotations

from src.ledger.extension.post import post_entry
from src.ledger.extension.repository import (
    SqlJournalRepository,
    create_journal_entry,
    post_journal_entry,
    validate_line_account_ownership,
    void_journal_entry,
)

__all__ = [
    "SqlJournalRepository",
    "create_journal_entry",
    "post_entry",
    "post_journal_entry",
    "validate_line_account_ownership",
    "void_journal_entry",
]
