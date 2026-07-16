"""Normal 1:1 and combination phase for reconciliation matching."""

from __future__ import annotations

from itertools import combinations
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, JournalEntryStatus
from src.reconciliation.base import (
    ReconciliationRepository,
    _candidate_is_better,
    entry_bank_side_amount,
    is_entry_balanced,
)
from src.reconciliation.extension.matching import (
    MatchingContext,
    _mark_auto_accepted_entry_reconciled,
    _within_combination_tolerance,
    prune_candidates,
    score_single,
)
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus


async def run_normal_matching_phase(
    db: AsyncSession,
    *,
    transactions: list[AtomicTransaction],
    matched_txn_ids: set[UUID],
    context: MatchingContext,
    repository: ReconciliationRepository,
    user_id: UUID,
) -> list[ReconciliationMatch]:
    """Run standard single and multi-entry candidate matching."""
    created_matches: list[ReconciliationMatch] = []
    for txn in transactions:
        if txn.id in matched_txn_ids:
            continue
        candidates = prune_candidates(
            context.get_candidates_for_date(txn.txn_date),
            txn_date=txn.txn_date,
            target_amount=txn.amount,
        )
        if not candidates:
            continue

        best_match = None
        history_score = await context.get_cached_pattern_score(txn)

        for entry in candidates:
            if not is_entry_balanced(entry):
                continue
            candidate = await score_single(
                db,
                txn,
                [entry],
                context.config,
                user_id=user_id,
                history_score=history_score,
            )
            if _candidate_is_better(candidate, best_match, context.entries_by_id):
                best_match = candidate

        for entry_a, entry_b in combinations(candidates, 2):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b)):
                continue
            combined = entry_bank_side_amount(entry_a, txn.direction) + entry_bank_side_amount(entry_b, txn.direction)
            if not _within_combination_tolerance(combined, txn, context.config):
                continue
            candidate = await score_single(
                db,
                txn,
                [entry_a, entry_b],
                context.config,
                user_id=user_id,
                history_score=history_score,
            )
            candidate.breakdown["multi_entry"] = 1
            if _candidate_is_better(candidate, best_match, context.entries_by_id):
                best_match = candidate

        for entry_a, entry_b, entry_c in combinations(candidates, 3):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b) and is_entry_balanced(entry_c)):
                continue
            combined = (
                entry_bank_side_amount(entry_a, txn.direction)
                + entry_bank_side_amount(entry_b, txn.direction)
                + entry_bank_side_amount(entry_c, txn.direction)
            )
            if not _within_combination_tolerance(combined, txn, context.config):
                continue
            candidate = await score_single(
                db,
                txn,
                [entry_a, entry_b, entry_c],
                context.config,
                user_id=user_id,
                history_score=history_score,
            )
            candidate.breakdown["multi_entry"] = 2
            if _candidate_is_better(candidate, best_match, context.entries_by_id):
                best_match = candidate

        if not best_match or best_match.score < context.config.pending_review:
            continue

        existing_match = await repository.get_active_match(txn.id)
        if existing_match:
            existing_je_ids = set(existing_match.journal_entry_ids or [])
            new_je_ids = set(best_match.journal_entry_ids or [])
            if existing_je_ids == new_je_ids:
                continue
            existing_match.status = ReconciliationStatus.SUPERSEDED

        status = (
            ReconciliationStatus.AUTO_ACCEPTED
            if best_match.score >= context.config.auto_accept
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
        await repository.add_match(match)

        if existing_match:
            await db.flush()
            existing_match.superseded_by_id = match.id

        created_matches.append(match)

        if status == ReconciliationStatus.AUTO_ACCEPTED and best_match.journal_entry_ids:
            entry_ids = [UUID(entry_id) for entry_id in best_match.journal_entry_ids]
            result = await db.execute(
                select(JournalEntry).where(JournalEntry.id.in_(entry_ids)).where(JournalEntry.user_id == user_id)
            )
            for entry in result.scalars():
                if entry.status != JournalEntryStatus.VOID:
                    _mark_auto_accepted_entry_reconciled(entry)
    return created_matches
