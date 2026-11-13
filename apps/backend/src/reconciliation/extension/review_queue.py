"""Reconciliation-match review queue: accept/reject/batch-accept + Stage 2 listing."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, JournalEntryStatus, JournalLine, current_anchored_journal_entries
from src.observability import get_logger
from src.reconciliation.base.errors import AmountMismatchError, EntryCreationError, MatchNotFoundError
from src.reconciliation.extension.entry_reads import entry_total_amount
from src.reconciliation.extension.matching import sync_reconciliation_matches_journal_entry_links_batch
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


async def _get_locked_pending_match(db: AsyncSession, match_id: UUID | str, user_id: UUID) -> ReconciliationMatch:
    """Fetch and lock a user-owned reconciliation match or raise MatchNotFoundError."""
    match = (
        await db.execute(
            select(ReconciliationMatch)
            .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
            .where(ReconciliationMatch.id == match_id, AtomicTransaction.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not match:
        raise MatchNotFoundError("Match not found")
    return match


async def accept_pending_matches(
    db: AsyncSession, matches: Sequence[ReconciliationMatch], *, user_id: UUID
) -> int:
    """Accept already-locked pending matches after entry-balance verification.

    Loads the transactions and every referenced journal entry once, checks each amount, flips the
    entries to RECONCILED, and syncs the anchor links once. Returns the count of reconciled entries
    that the accepted matches reference.
    """
    pending = [m for m in matches if m.status == ReconciliationStatus.PENDING_REVIEW]
    if not pending:
        return 0
    txns = {
        t.id: t
        for t in (
            await db.execute(select(AtomicTransaction).where(AtomicTransaction.id.in_({m.atomic_txn_id for m in pending})))
        ).scalars()
    }
    for match in pending:
        if match.journal_entry_ids or match.atomic_txn_id not in txns:
            continue
        existing_entry = (
            await db.execute(
                _anchored_entries(user_id=user_id, transaction_id=match.atomic_txn_id)
                .where(JournalEntry.status != JournalEntryStatus.VOID)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing_entry is None:
            raise EntryCreationError(
                "Authoritative economic disposition is required before accepting a reconciliation match; "
                "a pre-existing journal entry must exist, so post the source transaction first"
            )
        match.journal_entry_ids = [str(existing_entry.id)]

    entry_ids_by_match = {m: {UUID(e) for e in m.journal_entry_ids or []} for m in pending}
    all_ids = set().union(*entry_ids_by_match.values())
    entries = (
        {
            e.id: e
            for e in (
                await db.execute(
                    _anchored_entries(user_id=user_id)
                    .where(JournalEntry.id.in_(all_ids))
                    .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
                )
            ).scalars()
        }
        if all_ids
        else {}
    )
    for match in pending:
        ids = entry_ids_by_match[match]
        txn = txns.get(match.atomic_txn_id)
        if ids and txn:
            if not ids <= entries.keys():
                raise EntryCreationError(
                    "Reconciliation match references a journal entry without current decision authority"
                )
            total_entry_amount = sum(entry_total_amount(entries[i], currency=txn.currency) for i in ids)
            tolerance = max(txn.amount * Decimal("0.01"), Decimal("0.10"))
            if abs(total_entry_amount - txn.amount) > tolerance:
                raise AmountMismatchError(
                    f"Amount mismatch: transaction={txn.amount}, entries={total_entry_amount}, tolerance={tolerance}"
                )
        match.status = ReconciliationStatus.ACCEPTED
        match.version += 1
        for entry in (entries[i] for i in ids if i in entries):
            if entry.status != JournalEntryStatus.VOID:
                entry.status = JournalEntryStatus.RECONCILED
    await db.flush()
    await sync_reconciliation_matches_journal_entry_links_batch(db, pending, user_id=user_id, known_candidates=entries)
    return sum(
        entries[i].status == JournalEntryStatus.RECONCILED for ids in entry_ids_by_match.values() for i in ids if i in entries
    )


async def accept_match(
    db: AsyncSession,
    match_id: UUID,
    *,
    user_id: UUID,
) -> ReconciliationMatch:
    """Accept one pending reconciliation match after entry-balance verification."""
    match = await _get_locked_pending_match(db, match_id, user_id)
    await accept_pending_matches(db, [match], user_id=user_id)
    return match


async def reject_match(
    db: AsyncSession,
    match_id: str,
    *,
    user_id: UUID,
) -> ReconciliationMatch:
    """Reject a pending reconciliation match."""
    match = await _get_locked_pending_match(db, match_id, user_id)
    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    match.status = ReconciliationStatus.REJECTED
    match.version += 1
    await db.flush()
    return match


async def supersede_transaction_transfer_legs(
    db: AsyncSession,
    *,
    user_id: UUID,
    transaction_id: UUID,
    reason: str,
) -> None:
    """Find and supersede any active ReconciliationMatch and void any Processing transfer leg for transaction_id."""
    from src.ledger.extension.processing import find_processing_account
    from src.ledger.extension.repository import void_journal_entry

    matches_result = await db.execute(
        select(ReconciliationMatch)
        .where(ReconciliationMatch.atomic_txn_id == transaction_id)
        .where(ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)))
        .with_for_update()
    )
    active_matches = list(matches_result.scalars().all())

    entry_ids_to_void: set[UUID] = set()
    for match in active_matches:
        match.status = ReconciliationStatus.SUPERSEDED
        match.version += 1
        if match.journal_entry_ids:
            for jid in match.journal_entry_ids:
                try:
                    entry_ids_to_void.add(UUID(jid))
                except (ValueError, TypeError):
                    pass

    processing_account = await find_processing_account(db, user_id)
    if processing_account is not None:
        processing_entries_result = await db.execute(
            select(JournalEntry.id)
            .join(JournalLine, JournalEntry.id == JournalLine.journal_entry_id)
            .where(JournalEntry.user_id == user_id)
            .where(JournalEntry.source_id == transaction_id)
            .where(JournalEntry.status != JournalEntryStatus.VOID)
            .where(JournalLine.account_id == processing_account.id)
        )
        for eid in processing_entries_result.scalars().all():
            entry_ids_to_void.add(eid)

    for eid in entry_ids_to_void:
        entry = await db.get(JournalEntry, eid)
        if entry is not None and entry.status != JournalEntryStatus.VOID:
            await void_journal_entry(
                db,
                eid,
                reason=reason,
                user_id=user_id,
                allow_reconciled=True,
            )

    await db.flush()


async def release_transaction_dispositions(
    db: AsyncSession,
    *,
    user_id: UUID,
    transaction_ids: Sequence[UUID],
    reason: str,
) -> int:
    """Supersede the active matches of rows that a rejected or retired statement released (#2888).

    The caller names only rows that no other statement keeps. The call reads the rows of ``user_id`` alone.
    It voids no entry: the statement owner voids the entries after this call. A superseded match leaves
    every reader of current dispositions, so a transfer pair that held it is no longer a current pair.
    Return the number of matches that changed.
    """
    if not transaction_ids:
        return 0
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, AtomicTransaction.id == ReconciliationMatch.atomic_txn_id)
        .where(
            AtomicTransaction.user_id == user_id,
            ReconciliationMatch.atomic_txn_id.in_(list(transaction_ids)),
            ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)),
            ReconciliationMatch.superseded_by_id.is_(None),
        )
        .order_by(ReconciliationMatch.id)
        .with_for_update(of=ReconciliationMatch)
    )
    matches = list(result.scalars().all())
    for match in matches:
        match.status = ReconciliationStatus.SUPERSEDED
        match.version += 1
    await db.flush()
    logger.info("Released reconciliation dispositions", released=len(matches), reason=reason)
    return len(matches)


async def apply_reconciliation_feedback(
    db: AsyncSession,
    user_id: UUID,
    suggestion_id: UUID,
    action: str,
) -> Literal["accepted", "rejected", "recorded"]:
    """Apply user feedback from /ai/feedback to a pending reconciliation match (#2419).

    Delegates to ``reject_match`` for rejections and ``accept_match`` for acceptances when
    journal entries are linked; if the pending match has no linked journal entries yet,
    transitions the match directly to ``ACCEPTED`` so the review-band suggestion leaves
    the pending queue. Unknown, foreign, or already-decided ids return ``"recorded"``.
    """
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id == suggestion_id)
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .with_for_update(of=ReconciliationMatch)
    )
    match = result.scalar_one_or_none()
    if match is None:
        return "recorded"
    if action == "reject":
        await reject_match(db, str(match.id), user_id=user_id)
        return "rejected"
    try:
        await accept_match(db, match.id, user_id=user_id)
    except EntryCreationError:
        match.status = ReconciliationStatus.ACCEPTED
        match.version += 1
        await db.flush()
    return "accepted"


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
