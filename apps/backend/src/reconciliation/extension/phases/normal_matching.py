"""Normal 1:1 and combination phase for reconciliation matching."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, JournalEntryStatus
from src.reconciliation.base import ReconciliationRepository
from src.reconciliation.extension.candidate_policy import _normal_entry_combinations, prune_candidates
from src.reconciliation.extension.entry_reads import _candidate_is_better
from src.reconciliation.extension.matching import (
    MatchingContext,
    _mark_auto_accepted_entry_reconciled,
    score_single,
)
from src.reconciliation.orm.reconciliation import DispositionKind, ReconciliationMatch, ReconciliationStatus


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
            currency=txn.currency,
        )
        if not candidates:
            continue

        best_match = None
        history_score = await context.get_cached_pattern_score(txn)

        for entries in _normal_entry_combinations(
            txn,
            candidates,
            context.config,
            base_currency=context.base_currency,
        ):
            candidate = await score_single(
                db,
                txn,
                entries,
                context.config,
                user_id=user_id,
                history_score=history_score,
            )
            if len(entries) > 1:
                candidate.breakdown["multi_entry"] = len(entries) - 1
            if _candidate_is_better(candidate, best_match, context.entries_by_id):
                best_match = candidate

        if not best_match or best_match.score < context.config.pending_review:
            continue

        existing_match = await repository.claim_transaction(txn.id)
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
        match.disposition_kind = DispositionKind.JOURNAL_MATCH
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
