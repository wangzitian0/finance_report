"""AsyncSession adapter for the reconciliation repository port."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.journal import JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicTransaction
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.reconciliation.base.repository import ReconciliationRepository


class SqlReconciliationRepository(ReconciliationRepository):
    """SQLAlchemy adapter implementing reconciliation read/write operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_pending_transactions(
        self,
        user_id: UUID,
        limit: int | None = None,
    ) -> list[AtomicTransaction]:
        subquery = select(ReconciliationMatch.atomic_txn_id).where(ReconciliationMatch.atomic_txn_id.isnot(None))
        query = (
            select(AtomicTransaction)
            .where(AtomicTransaction.user_id == user_id)
            .where(AtomicTransaction.id.notin_(subquery))
            .order_by(AtomicTransaction.txn_date)
        )
        if limit:
            query = query.limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def list_journal_candidates(
        self,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[JournalEntry]:
        result = await self._db.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == user_id)
            .where(JournalEntry.entry_date.between(start_date, end_date))
            .where(JournalEntry.status != JournalEntryStatus.VOID)
            .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
        )
        return list(result.scalars().all())

    async def get_active_match(self, txn_id: UUID) -> ReconciliationMatch | None:
        result = await self._db.execute(
            select(ReconciliationMatch).where(
                ReconciliationMatch.atomic_txn_id == txn_id,
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
                ReconciliationMatch.superseded_by_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def add_match(self, match: ReconciliationMatch) -> None:
        self._db.add(match)
