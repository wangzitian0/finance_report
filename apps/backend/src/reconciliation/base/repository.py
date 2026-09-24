"""Reconciliation repository port (base layer)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from src.extraction import AtomicTransaction
    from src.ledger import JournalEntry
    from src.reconciliation import ReconciliationMatch


class ReconciliationRepository(Protocol):
    """Port for reconciliation matching reads/writes."""

    async def list_pending_transactions(self, user_id: UUID, limit: int | None = None) -> list[AtomicTransaction]: ...

    async def list_journal_candidates(
        self,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[JournalEntry]: ...

    async def get_active_match(self, txn_id: UUID) -> ReconciliationMatch | None: ...

    async def claim_transaction(self, txn_id: UUID) -> ReconciliationMatch | None:
        """Serialize disposition selection and return an existing active winner."""
        ...

    async def add_match(self, match: ReconciliationMatch) -> None: ...
