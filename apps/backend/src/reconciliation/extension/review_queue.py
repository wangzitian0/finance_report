"""Reconciliation-match review queue: accept/reject/batch-accept + Stage 2 listing."""

from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, JournalEntryStatus, JournalLine, current_anchored_journal_entries
from src.observability import get_logger
from src.reconciliation.base.config import entry_total_amount
from src.reconciliation.base.errors import AmountMismatchError, EntryCreationError, MatchNotFoundError
from src.reconciliation.extension.matching import sync_reconciliation_match_journal_entry_links
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus

logger = get_logger(__name__)


def _anchored_entries(*, user_id: UUID, transaction_id: UUID | None = None):
    """Return entries whose exact command was validated before persistence.

    The journal owns only an immutable decision id. Audit's projection resolves
    its current target and causal authority from the canonical TraceRecord graph.
    """
    query = current_anchored_journal_entries(user_id=user_id)
    if transaction_id is not None:
        query = current_anchored_journal_entries(
            user_id=user_id,
            target_kind="journal_command",
            target_id=f"statement-transaction:{transaction_id}",
        )
    return query


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
    )
    return cast(list[ReconciliationMatch], result.scalars().all())


async def count_pending_review_items(db: AsyncSession, *, user_id: UUID) -> int:
    """Return the exact user-scoped count for workflow-level review prompts."""
    return int(
        await db.scalar(
            select(func.count(ReconciliationMatch.id))
            .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
            .where(AtomicTransaction.user_id == user_id)
            .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        )
        or 0
    )


async def accept_match(
    db: AsyncSession,
    match_id: UUID,
    *,
    user_id: UUID,
) -> ReconciliationMatch:
    """Accept a pending reconciliation match.

    Amount validation is unconditional: entry balance validation is never
    skippable (red line; the former ``skip_amount_validation`` flag had zero
    production callers and existed only to bypass it — removed in #1864).

    Args:
        db: Database session
        match_id: ID of the match to accept
        user_id: User ID for authorization

    Raises:
        ReconciliationError: If match not found or amount validation fails
    """
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id == match_id)
        .where(AtomicTransaction.user_id == user_id)
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise MatchNotFoundError("Match not found")

    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    txn = await db.get(AtomicTransaction, match.atomic_txn_id)

    if txn and not match.journal_entry_ids:
        existing_entry_result = await db.execute(
            _anchored_entries(user_id=user_id, transaction_id=txn.id)
            .where(JournalEntry.status != JournalEntryStatus.VOID)
            .limit(1)
            .with_for_update()
        )
        existing_entry = existing_entry_result.scalar_one_or_none()
        if existing_entry:
            match.journal_entry_ids = [str(existing_entry.id)]
        else:
            raise EntryCreationError(
                "Authoritative economic disposition is required before accepting a reconciliation match; "
                "a pre-existing journal entry must exist, so post the source transaction first"
            )

    # Validate that journal entry amounts match transaction amount
    if match.journal_entry_ids and txn:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        entries_result = await db.execute(
            _anchored_entries(user_id=user_id)
            .where(JournalEntry.id.in_(entry_ids))
            .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
        )
        entries = list(entries_result.scalars())
        if len(entries) != len(set(entry_ids)):
            raise EntryCreationError(
                "Reconciliation match references a journal entry without current decision authority"
            )

        # Use entry_total_amount() to correctly sum all debit lines
        total_entry_amount = sum(entry_total_amount(entry) for entry in entries)

        # Allow 1% tolerance or $0.10, whichever is greater
        tolerance = max(txn.amount * Decimal("0.01"), Decimal("0.10"))
        if abs(total_entry_amount - txn.amount) > tolerance:
            raise AmountMismatchError(
                f"Amount mismatch: transaction={txn.amount}, entries={total_entry_amount}, tolerance={tolerance}"
            )

    match.status = ReconciliationStatus.ACCEPTED
    match.version += 1

    if match.journal_entry_ids:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        reconciled_entries_result = await db.execute(
            select(JournalEntry).where(JournalEntry.id.in_(entry_ids)).where(JournalEntry.user_id == user_id)
        )
        for entry in reconciled_entries_result.scalars():
            if entry.status != JournalEntryStatus.VOID:
                entry.status = JournalEntryStatus.RECONCILED

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
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise MatchNotFoundError("Match not found")

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

    # Join atomic transaction to authorize by user_id (#1675 D4: no relationship()
    # eager-load — accept_match() below re-fetches the transaction by id itself).
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id.in_(match_ids))
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.match_score >= min_score)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
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
        accepted.append(
            await accept_match(
                db,
                match.id,
                user_id=user_id,
            )
        )

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
        .limit(50)
    )
    if run_id:
        query = query.where(ReconciliationMatch.run_id == run_id)

    result = await db.execute(query)
    return list(result.scalars().all())
