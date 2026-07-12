"""Reconciliation-match review queue: accept/reject/batch-accept + Stage 2 listing.

Journal-entry creation itself lives in extraction (``AtomicTransaction`` is
extraction's aggregate; reconciliation depends on extraction, never the
reverse) — see ``src.extraction.extension.review_queue.create_entry_from_txn``.
"""

from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType, promote_entry_source_type
from src.extraction import create_entry_from_txn
from src.ledger import JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicTransaction
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.observability import get_logger
from src.reconciliation.base.config import entry_total_amount
from src.reconciliation.extension.matching import sync_reconciliation_match_journal_entry_links

logger = get_logger(__name__)


async def get_pending_items(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ReconciliationMatch]:
    """Return pending review reconciliation matches."""
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .order_by(ReconciliationMatch.match_score.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
    )
    return cast(list[ReconciliationMatch], result.scalars().all())


async def accept_match(
    db: AsyncSession,
    match_id: str,
    *,
    user_id: UUID,
    skip_amount_validation: bool = False,
) -> ReconciliationMatch:
    """Accept a pending reconciliation match.

    Args:
        db: Database session
        match_id: ID of the match to accept
        user_id: User ID for authorization
        skip_amount_validation: If True, skip amount sum validation (for edge cases)

    Raises:
        ValueError: If match not found or amount validation fails
    """
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id == match_id)
        .where(AtomicTransaction.user_id == user_id)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise ValueError("Match not found")

    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    txn = match.atomic_transaction

    if txn and not match.journal_entry_ids:
        existing_entry_result = await db.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == user_id)
            .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
            .where(JournalEntry.source_id == txn.id)
            .where(JournalEntry.status != JournalEntryStatus.VOID)
            .limit(1)
            .with_for_update()
        )
        existing_entry = existing_entry_result.scalar_one_or_none()
        if existing_entry:
            match.journal_entry_ids = [str(existing_entry.id)]
        else:
            created_entry = await create_entry_from_txn(db, txn, user_id=user_id, auto_post=True)
            match.journal_entry_ids = [str(created_entry.id)]

    # Validate that journal entry amounts match transaction amount
    if match.journal_entry_ids and txn and not skip_amount_validation:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        entries_result = await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id.in_(entry_ids))
            .where(JournalEntry.user_id == user_id)
            .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
        )
        entries = list(entries_result.scalars())

        # Use entry_total_amount() to correctly sum all debit lines
        total_entry_amount = sum(entry_total_amount(entry) for entry in entries)

        # Allow 1% tolerance or $0.10, whichever is greater
        tolerance = max(txn.amount * Decimal("0.01"), Decimal("0.10"))
        if abs(total_entry_amount - txn.amount) > tolerance:
            raise ValueError(
                f"Amount mismatch: transaction={txn.amount}, entries={total_entry_amount}, tolerance={tolerance}"
            )

    match.status = ReconciliationStatus.ACCEPTED
    match.version += 1

    if match.journal_entry_ids:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        result = await db.execute(
            select(JournalEntry).where(JournalEntry.id.in_(entry_ids)).where(JournalEntry.user_id == user_id)
        )
        for entry in result.scalars():
            if entry.status != JournalEntryStatus.VOID:
                entry.status = JournalEntryStatus.RECONCILED
                promote_entry_source_type(entry, JournalEntrySourceType.USER_CONFIRMED)

    await db.flush()
    await sync_reconciliation_match_journal_entry_links(db, match)
    return match


async def reject_match(
    db: AsyncSession,
    match_id: str,
    *,
    user_id: UUID,
) -> ReconciliationMatch:
    """Reject a pending reconciliation match."""
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id == match_id)
        .where(AtomicTransaction.user_id == user_id)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise ValueError("Match not found")

    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    match.status = ReconciliationStatus.REJECTED
    match.version += 1

    await db.flush()
    return match


async def batch_accept(
    db: AsyncSession,
    match_ids: list[str],
    *,
    user_id: UUID,
    min_score: int = 80,
) -> list[ReconciliationMatch]:
    """Batch accept high-score matches."""
    if not match_ids:
        return []

    # Optimization: join atomic transaction and load it to avoid N+1 queries later
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id.in_(match_ids))
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.match_score >= min_score)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .with_for_update(of=ReconciliationMatch)
    )
    matches = result.scalars().all()
    matched_ids = {str(m.id) for m in matches}
    skipped_ids = set(match_ids) - matched_ids
    if skipped_ids:
        logger.info(
            "batch_accept: %d of %d matches skipped (score < %d or not pending): %s",
            len(skipped_ids),
            len(match_ids),
            min_score,
            list(skipped_ids),
        )

    accepted: list[ReconciliationMatch] = []
    for match in matches:
        accepted.append(await accept_match(db, str(match.id), user_id=user_id))

    await db.flush()
    return accepted


async def get_stage2_queue(
    db: AsyncSession,
    user_id: UUID,
    run_id: str | None = None,
) -> list[ReconciliationMatch]:
    """Return matches pending Stage 2 review for a user."""
    query = (
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            AtomicTransaction.user_id == user_id,
        )
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .limit(50)
    )
    if run_id:
        query = query.where(ReconciliationMatch.run_id == run_id)

    result = await db.execute(query)
    return list(result.scalars().all())
