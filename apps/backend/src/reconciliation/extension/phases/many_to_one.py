"""Many-to-one phase for reconciliation matching."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntryStatus
from src.reconciliation.base import ReconciliationRepository, _candidate_is_better, is_entry_balanced
from src.reconciliation.extension.matching import (
    MatchingContext,
    _mark_auto_accepted_entry_reconciled,
    build_many_to_one_groups,
    prune_candidates,
    score_group,
)
from src.reconciliation.orm.reconciliation import DispositionKind, ReconciliationMatch, ReconciliationStatus


async def run_many_to_one_phase(
    db: AsyncSession,
    *,
    transactions: list[AtomicTransaction],
    matched_txn_ids: set[UUID],
    context: MatchingContext,
    repository: ReconciliationRepository,
    user_id: UUID,
) -> list[ReconciliationMatch]:
    """Run many-to-one grouping and candidate scoring."""
    created_matches: list[ReconciliationMatch] = []
    groups = build_many_to_one_groups(transactions)
    for group in groups:
        if all(txn.id in matched_txn_ids for txn in group):
            continue
        group_total = sum((txn.amount for txn in group), Decimal("0.00"))
        group_date = max(txn.txn_date for txn in group)
        candidates = context.get_candidates_for_date(group_date)
        if not candidates:
            continue
        candidates = prune_candidates(
            candidates,
            txn_date=group_date,
            target_amount=group_total,
            currency=group[0].currency,
        )

        best_candidate = None
        best_entry = None
        history_score = await context.get_cached_pattern_score(group[0])

        for entry in candidates:
            if not is_entry_balanced(entry, base_currency=context.base_currency):
                continue

            candidate = await score_group(
                db,
                group[0],
                [entry],
                context.config,
                user_id=user_id,
                group_amount=group_total,
                history_score=history_score,
            )
            candidate.breakdown["group_total"] = str(group_total)
            if candidate.score >= context.config.pending_review and _candidate_is_better(
                candidate, best_candidate, context.entries_by_id
            ):
                best_candidate = candidate
                best_entry = entry

        if best_candidate and best_entry:
            status = (
                ReconciliationStatus.AUTO_ACCEPTED
                if best_candidate.score >= context.config.auto_accept
                else ReconciliationStatus.PENDING_REVIEW
            )
            for txn in group:
                if txn.id in matched_txn_ids:
                    continue
                existing_match = await repository.claim_transaction(txn.id)
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
                match.disposition_kind = DispositionKind.JOURNAL_MATCH
                await repository.add_match(match)

                if existing_match:
                    await db.flush()
                    existing_match.superseded_by_id = match.id

                created_matches.append(match)
                matched_txn_ids.add(txn.id)
                if status == ReconciliationStatus.AUTO_ACCEPTED and best_entry.status != JournalEntryStatus.VOID:
                    _mark_auto_accepted_entry_reconciled(best_entry)
    return created_matches
