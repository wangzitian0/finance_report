"""Many-to-one phase for reconciliation matching."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import JournalEntry, JournalEntryStatus
from src.models.layer2 import AtomicTransaction
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus


async def run_many_to_one_phase(
    db: AsyncSession,
    *,
    transactions: list[AtomicTransaction],
    matched_txn_ids: set[UUID],
    matches: list[ReconciliationMatch],
    get_candidates_for_date,
    get_cached_pattern_score,
    entries_by_id: dict[str, JournalEntry],
    config,
    user_id: UUID,
    get_existing_active_match,
    calculate_match_score,
    build_many_to_one_groups,
    prune_candidates,
    is_entry_balanced,
    candidate_is_better,
    mark_auto_accepted,
) -> None:
    """Run many-to-one grouping and candidate scoring."""
    groups = build_many_to_one_groups(transactions)
    for group in groups:
        if all(txn.id in matched_txn_ids for txn in group):
            continue
        group_total = sum((txn.amount for txn in group), Decimal("0.00"))
        group_date = max(txn.txn_date for txn in group)
        candidates = get_candidates_for_date(group_date)
        if not candidates:
            continue
        candidates = prune_candidates(
            candidates,
            txn_date=group_date,
            target_amount=group_total,
        )

        best_candidate = None
        best_entry = None
        history_score = await get_cached_pattern_score(group[0])

        for entry in candidates:
            if not is_entry_balanced(entry):
                continue

            candidate = await calculate_match_score(
                db,
                group[0],
                [entry],
                config,
                user_id=user_id,
                is_multi=True,
                is_many_to_one=True,
                amount_override=group_total,
                history_score_override=history_score,
            )
            candidate.breakdown["group_total"] = str(group_total)
            if candidate.score >= config.pending_review and candidate_is_better(
                candidate, best_candidate, entries_by_id
            ):
                best_candidate = candidate
                best_entry = entry

        if best_candidate and best_entry:
            status = (
                ReconciliationStatus.AUTO_ACCEPTED
                if best_candidate.score >= config.auto_accept
                else ReconciliationStatus.PENDING_REVIEW
            )
            for txn in group:
                if txn.id in matched_txn_ids:
                    continue
                existing_match = await get_existing_active_match(db, txn.id)
                if existing_match:
                    existing_je_ids = set(existing_match.journal_entry_ids or [])
                    new_je_ids = set(best_candidate.journal_entry_ids or [])
                    if existing_je_ids == new_je_ids:
                        matched_txn_ids.add(txn.id)
                        continue
                    existing_match.status = ReconciliationStatus.SUPERSEDED

                match_kwargs = {
                    "journal_entry_ids": best_candidate.journal_entry_ids,
                    "match_score": best_candidate.score,
                    "score_breakdown": best_candidate.breakdown,
                    "status": status,
                }
                match_kwargs["atomic_txn_id"] = txn.id

                match = ReconciliationMatch(**match_kwargs)
                db.add(match)

                if existing_match:
                    await db.flush()
                    existing_match.superseded_by_id = match.id

                matches.append(match)
                matched_txn_ids.add(txn.id)
                if status == ReconciliationStatus.AUTO_ACCEPTED and best_entry.status != JournalEntryStatus.VOID:
                    mark_auto_accepted(best_entry)
