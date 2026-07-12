"""Reconciliation repository port (base layer)."""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from src.ledger import JournalEntry
from src.models.layer2 import AtomicTransaction
from src.models.reconciliation import ReconciliationMatch


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

    async def add_match(self, match: ReconciliationMatch) -> None: ...
