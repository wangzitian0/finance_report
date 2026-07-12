"""Normal 1:1 and combination phase for reconciliation matching."""

from __future__ import annotations

from itertools import combinations
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, JournalEntryStatus
from src.reconciliation import ReconciliationMatch, ReconciliationStatus


async def run_normal_matching_phase(
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
    candidate_is_better,
    prune_candidates,
    is_entry_balanced,
    within_combination_tolerance,
    entry_bank_side_amount,
    mark_auto_accepted,
) -> None:
    """Run standard single and multi-entry candidate matching."""
    for txn in transactions:
        if txn.id in matched_txn_ids:
            continue
        candidates = prune_candidates(
            get_candidates_for_date(txn.txn_date),
            txn_date=txn.txn_date,
            target_amount=txn.amount,
        )
        if not candidates:
            continue

        best_match = None
        history_score = await get_cached_pattern_score(txn)

        for entry in candidates:
            if not is_entry_balanced(entry):
                continue
            candidate = await calculate_match_score(
                db, txn, [entry], config, user_id=user_id, history_score_override=history_score
            )
            if candidate_is_better(candidate, best_match, entries_by_id):
                best_match = candidate

        for entry_a, entry_b in combinations(candidates, 2):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b)):
                continue
            combined = entry_bank_side_amount(entry_a, txn.direction) + entry_bank_side_amount(entry_b, txn.direction)
            if not within_combination_tolerance(combined, txn, config):
                continue
            candidate = await calculate_match_score(
                db,
                txn,
                [entry_a, entry_b],
                config,
                user_id=user_id,
                is_multi=True,
                history_score_override=history_score,
            )
            candidate.breakdown["multi_entry"] = 1
            if candidate_is_better(candidate, best_match, entries_by_id):
                best_match = candidate

        for entry_a, entry_b, entry_c in combinations(candidates, 3):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b) and is_entry_balanced(entry_c)):
                continue
            combined = (
                entry_bank_side_amount(entry_a, txn.direction)
                + entry_bank_side_amount(entry_b, txn.direction)
                + entry_bank_side_amount(entry_c, txn.direction)
            )
            if not within_combination_tolerance(combined, txn, config):
                continue
            candidate = await calculate_match_score(
                db,
                txn,
                [entry_a, entry_b, entry_c],
                config,
                user_id=user_id,
                is_multi=True,
                history_score_override=history_score,
            )
            candidate.breakdown["multi_entry"] = 2
            if candidate_is_better(candidate, best_match, entries_by_id):
                best_match = candidate

        if not best_match or best_match.score < config.pending_review:
            continue

        existing_match = await get_existing_active_match(db, txn.id)
        if existing_match:
            existing_je_ids = set(existing_match.journal_entry_ids or [])
            new_je_ids = set(best_match.journal_entry_ids or [])
            if existing_je_ids == new_je_ids:
                continue
            existing_match.status = ReconciliationStatus.SUPERSEDED

        status = (
            ReconciliationStatus.AUTO_ACCEPTED
            if best_match.score >= config.auto_accept
            else ReconciliationStatus.PENDING_REVIEW
        )
        match_kwargs = {
            "journal_entry_ids": best_match.journal_entry_ids,
            "match_score": best_match.score,
            "score_breakdown": best_match.breakdown,
            "status": status,
        }
        match_kwargs["atomic_txn_id"] = txn.id

        match = ReconciliationMatch(**match_kwargs)
        db.add(match)

        if existing_match:
            await db.flush()
            existing_match.superseded_by_id = match.id

        matches.append(match)

        if status == ReconciliationStatus.AUTO_ACCEPTED and best_match.journal_entry_ids:
            entry_ids = [UUID(entry_id) for entry_id in best_match.journal_entry_ids]
            result = await db.execute(
                select(JournalEntry).where(JournalEntry.id.in_(entry_ids)).where(JournalEntry.user_id == user_id)
            )
            for entry in result.scalars():
                if entry.status != JournalEntryStatus.VOID:
                    mark_auto_accepted(entry)
