"""AsyncSession adapter for the reconciliation repository port."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import STATEMENT_SOURCE_TYPES
from src.extraction import effective_statement_transaction_filter
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, JournalEntryStatus, JournalLine, current_anchored_journal_entries
from src.reconciliation.base.repository import ReconciliationRepository
from src.reconciliation.orm.reconciliation import (
    DispositionKind,
    ReconciliationMatch,
    ReconciliationMatchJournalEntry,
    ReconciliationStatus,
)


def posted_statement_source_ids(user_id: UUID) -> Select:
    """Select statement transaction IDs that already have a live statement-posted journal entry."""
    return (
        current_anchored_journal_entries(
            user_id=user_id,
            target_kind="journal_command",
            target_id=func.concat("statement-transaction:", JournalEntry.source_id),
        )
        .with_only_columns(JournalEntry.source_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.status != JournalEntryStatus.VOID)
    )


class SqlReconciliationRepository(ReconciliationRepository):
    """SQLAlchemy adapter implementing reconciliation read/write operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_pending_transactions(
        self,
        user_id: UUID,
        limit: int | None = None,
    ) -> list[AtomicTransaction]:
        # Rejected suggestions are deliberately not retried automatically: the
        # manual unmatched queue owns recovery without overturning human review.
        subquery = select(ReconciliationMatch.atomic_txn_id).where(
            ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            ReconciliationMatch.superseded_by_id.is_(None),
        )
        query = (
            select(AtomicTransaction)
            .where(effective_statement_transaction_filter(user_id))
            .where(AtomicTransaction.id.notin_(subquery))
            .where(AtomicTransaction.id.notin_(posted_statement_source_ids(user_id)))
            .order_by(AtomicTransaction.txn_date)
        )
        if limit is not None:
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
        claimed_journal_entries = (
            select(ReconciliationMatchJournalEntry.journal_entry_id)
            .join(ReconciliationMatch, ReconciliationMatch.id == ReconciliationMatchJournalEntry.match_id)
            .where(
                ReconciliationMatch.disposition_kind == DispositionKind.JOURNAL_MATCH,
                ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)),
                ReconciliationMatch.superseded_by_id.is_(None),
            )
        )
        result = await self._db.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == user_id)
            .where(JournalEntry.entry_date.between(start_date, end_date))
            .where(JournalEntry.status.notin_((JournalEntryStatus.VOID, JournalEntryStatus.RECONCILED)))
            .where(JournalEntry.id.notin_(claimed_journal_entries))
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

    async def _lock_transaction(self, txn_id: UUID) -> None:
        """Lock the immutable source row. A second request waits until the first request ends."""
        await self._db.execute(select(AtomicTransaction.id).where(AtomicTransaction.id == txn_id).with_for_update())

    async def claim_transaction(self, txn_id: UUID) -> ReconciliationMatch | None:
        """Lock the immutable source row before selecting its disposition head."""
        await self._lock_transaction(txn_id)
        return await self.get_active_match(txn_id)

    async def claim_transaction_for_decision(self, txn_id: UUID) -> ReconciliationMatch | None:
        """Lock the source row, then return the match that owns it for a decision of a person.

        The background run keeps the stricter ``claim_transaction``: it must not overturn a rejection.
        A person asks for a new disposition on purpose. A rejected suggestion is history then, as in the
        active match index and in ``submit_reviewed_disposition``.
        """
        await self._lock_transaction(txn_id)
        result = await self._db.execute(
            select(ReconciliationMatch).where(
                ReconciliationMatch.atomic_txn_id == txn_id,
                ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)),
                ReconciliationMatch.superseded_by_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def add_match(self, match: ReconciliationMatch) -> None:
        self._db.add(match)
