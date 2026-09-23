"""Reconciliation matching engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, promote_entry_source_type
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import (
    JournalEntry,
    JournalEntryStatus,
    find_transfer_pairs,
)
from src.llm import ai_semantic_score
from src.observability import get_logger, record_reconciliation_match_outcome
from src.reconciliation.base.config import (
    MatchCandidate,
    ReconciliationConfig,
)
from src.reconciliation.base.prompts import build_reconciliation_prompt
from src.reconciliation.base.repository import ReconciliationRepository
from src.reconciliation.extension.candidate_policy import _score_rule_candidate
from src.reconciliation.extension.config import load_reconciliation_config
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.extension.scoring import extract_merchant_tokens, score_description, score_pattern
from src.reconciliation.extension.transfer_pairs import persist_transfer_pairs
from src.reconciliation.orm.reconciliation import (
    ReconciliationMatch,
    ReconciliationMatchJournalEntry,
    ReconciliationStatus,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class MatchingContext:
    """Stable dependencies shared by the matching phases.

    Only the two run-scoped closures live here; package-level matching helpers
    are imported by the phases directly instead of being passed as untyped
    function parameters.
    """

    config: ReconciliationConfig
    base_currency: str
    entries_by_id: dict[str, JournalEntry]
    get_candidates_for_date: Callable[[date], list[JournalEntry]]
    get_cached_pattern_score: Callable[[AtomicTransaction], Awaitable[float]]


async def _calculate_candidate_score(
    db: AsyncSession,
    transaction: AtomicTransaction,
    entries: list[JournalEntry],
    config: ReconciliationConfig,
    user_id: UUID,
    *,
    amount: Decimal,
    is_group: bool,
    history_score: float | None,
) -> MatchCandidate:
    """Calculate the common score after the public mode selected semantics."""
    if history_score is None:
        history_score = await score_pattern(db, transaction, config, user_id=user_id)
    candidate = _score_rule_candidate(
        transaction,
        entries,
        config,
        amount=amount,
        is_group=is_group,
        history_score=history_score,
    )
    total = candidate.score
    scores = candidate.breakdown

    # EPIC-018 Phase 3: Hybrid scoring for ambiguous matches (60-84 range)
    if config.enable_ai_reconciliation and 60 <= total <= 84:
        primary_entry = entries[0] if entries else None
        if primary_entry:
            date_diff = abs((transaction.txn_date - primary_entry.entry_date).days)
            amount_pct = float(scores.get("amount", 0.0))
            # llm's ai_semantic_score is generic (prompt in, score out); the
            # reconciliation-specific prompt is built here, package-side.
            prompt = build_reconciliation_prompt(
                txn_description=transaction.description,
                entry_memo=primary_entry.memo or "",
                date_diff_days=date_diff,
                amount_match_pct=amount_pct,
            )
            semantic = await ai_semantic_score(prompt)
            # Hybrid formula: 70% algorithmic + 30% AI semantic
            total = int(round(Decimal("0.7") * total + Decimal("0.3") * semantic, 0))
            scores["ai_semantic"] = float(semantic)
            scores["hybrid_applied"] = 1.0

    candidate.score = total
    return candidate


async def score_single(
    db: AsyncSession,
    transaction: AtomicTransaction,
    entries: list[JournalEntry],
    config: ReconciliationConfig,
    user_id: UUID,
    *,
    history_score: float | None = None,
) -> MatchCandidate:
    """Score a normal single- or multi-entry candidate against one transaction."""
    return await _calculate_candidate_score(
        db,
        transaction,
        entries,
        config,
        user_id,
        amount=transaction.amount,
        is_group=False,
        history_score=history_score,
    )


async def score_group(
    db: AsyncSession,
    transaction: AtomicTransaction,
    entries: list[JournalEntry],
    config: ReconciliationConfig,
    user_id: UUID,
    *,
    group_amount: Decimal,
    history_score: float | None = None,
) -> MatchCandidate:
    """Score a many-transactions-to-one-entry candidate with its group total."""
    return await _calculate_candidate_score(
        db,
        transaction,
        entries,
        config,
        user_id,
        amount=group_amount,
        is_group=True,
        history_score=history_score,
    )


async def calculate_match_score(
    db: AsyncSession,
    transaction: AtomicTransaction,
    entries: list[JournalEntry],
    config: ReconciliationConfig,
    user_id: UUID,
    *,
    history_score_override: float | None = None,
) -> MatchCandidate:
    """Compatibility name for normal scoring; group callers use ``score_group``."""
    return await score_single(
        db,
        transaction,
        entries,
        config,
        user_id,
        history_score=history_score_override,
    )


async def find_candidates(
    db: AsyncSession,
    txn_date: date,
    config: ReconciliationConfig,
    user_id: UUID,
) -> list[JournalEntry]:
    """Find journal entry candidates near a transaction date."""
    date_start = txn_date - timedelta(days=config.date_days)
    date_end = txn_date + timedelta(days=config.date_days)
    return await SqlReconciliationRepository(db).list_journal_candidates(
        user_id=user_id,
        start_date=date_start,
        end_date=date_end,
    )


async def _get_pending_layer2_transactions(
    db: AsyncSession, user_id: UUID, limit: int | None = None
) -> list[AtomicTransaction]:
    """Compatibility wrapper over the single repository-owned pending query."""
    return await SqlReconciliationRepository(db).list_pending_transactions(user_id, limit)


async def _get_existing_active_match(
    db: AsyncSession,
    txn_id: UUID,
) -> ReconciliationMatch | None:
    """Compatibility wrapper over the single repository-owned active query."""
    return await SqlReconciliationRepository(db).get_active_match(txn_id)


async def accepted_transfer_txn_ids(
    db: AsyncSession,
    txn_ids: Sequence[UUID],
) -> set[UUID]:
    """Atomic-transaction ids covered by a live accepted match with journal entries.

    The read behind extraction's transfer-exclusions provider port (#1675 D5):
    statement posting skips txns an accepted/auto-accepted, non-superseded
    match already anchors to journal entries. Published on the package root;
    the app composition root (``src/main.py``) registers it into
    the extraction-owned statement ingestion use case at composition time
    (reconciliation depends on extraction, never the reverse).
    """
    ids = list(txn_ids)
    if not ids:
        return set()
    result = await db.execute(
        select(ReconciliationMatch)
        .where(ReconciliationMatch.atomic_txn_id.in_(ids))
        .where(
            ReconciliationMatch.status.in_([ReconciliationStatus.AUTO_ACCEPTED, ReconciliationStatus.ACCEPTED]),
            ReconciliationMatch.superseded_by_id.is_(None),
        )
    )
    return {match.atomic_txn_id for match in result.scalars().all() if match.journal_entry_ids}


def _mark_auto_accepted_entry_reconciled(entry: JournalEntry) -> None:
    was_immutable = entry.status in (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)
    entry.status = JournalEntryStatus.RECONCILED
    if not was_immutable:
        promote_entry_source_type(entry, JournalEntrySourceType.AUTO_MATCHED)


async def execute_matching(
    db: AsyncSession,
    *,
    user_id: UUID,
    currency: str,
    limit: int | None = None,
    repository: ReconciliationRepository | None = None,
) -> list[ReconciliationMatch]:
    """Execute reconciliation matching for pending transactions."""
    config = load_reconciliation_config()
    repo = repository if repository is not None else SqlReconciliationRepository(db)

    # Read pending transactions from Layer 2 (atomic_transactions).
    transactions = await repo.list_pending_transactions(user_id, limit)

    if not transactions:
        return []

    # Optimization: Pre-fetch all candidates for the entire period to avoid N+1 find_candidates
    min_date = min(txn.txn_date for txn in transactions) - timedelta(days=config.date_days)
    max_date = max(txn.txn_date for txn in transactions) + timedelta(days=config.date_days)

    all_candidates = await repo.list_journal_candidates(
        user_id=user_id,
        start_date=min_date,
        end_date=max_date,
    )
    entries_by_id = {str(entry.id): entry for entry in all_candidates}

    def get_candidates_for_date(txn_date: date) -> list[JournalEntry]:
        d_start = txn_date - timedelta(days=config.date_days)
        d_end = txn_date + timedelta(days=config.date_days)
        return [c for c in all_candidates if d_start <= c.entry_date <= d_end]

    matches: list[ReconciliationMatch] = []
    matched_txn_ids: set[UUID] = set()

    # Optimization: Cache pattern scores to avoid repeated DB hits for similar merchants
    pattern_score_cache: dict[str, float] = {}

    async def get_cached_pattern_score(txn: AtomicTransaction) -> float:
        tokens = extract_merchant_tokens(txn.description)
        if not tokens:
            return 0.0
        token = tokens[0]
        if token in pattern_score_cache:
            return pattern_score_cache[token]
        score = await score_pattern(db, txn, config, user_id=user_id)
        pattern_score_cache[token] = score
        return score

    context = MatchingContext(
        config=config,
        base_currency=currency,
        entries_by_id=entries_by_id,
        get_candidates_for_date=get_candidates_for_date,
        get_cached_pattern_score=get_cached_pattern_score,
    )

    # Imported after this module's helpers are defined so phase modules can
    # import the shared typed helpers without a module-initialization cycle.
    from src.reconciliation.extension.phases import (
        run_many_to_one_phase,
        run_normal_matching_phase,
        run_transfer_detection_phase,
    )

    # Journal evidence is authoritative; keyword-based transfer detection is
    # only a fallback for transactions left without a disposition.
    matches.extend(
        await run_many_to_one_phase(
            db,
            transactions=transactions,
            matched_txn_ids=matched_txn_ids,
            context=context,
            repository=repo,
            user_id=user_id,
        )
    )

    matches.extend(
        await run_normal_matching_phase(
            db,
            transactions=transactions,
            matched_txn_ids=matched_txn_ids,
            context=context,
            repository=repo,
            user_id=user_id,
        )
    )

    matches.extend(
        await run_transfer_detection_phase(
            db,
            transactions=transactions,
            matched_txn_ids=matched_txn_ids,
            repository=repo,
            user_id=user_id,
        )
    )

    # Materialize normalized anchors before pairing so pair persistence resolves
    # ledger entries back to the winning disposition heads.
    try:
        await db.flush()
        for match in matches:
            await sync_reconciliation_match_journal_entry_links(db, match)
    except Exception as e:
        logger.error(
            "Reconciliation flush failed",
            user_id=str(user_id),
            matches_attempted=len(matches),
            error=str(e),
            error_type=type(e).__name__,
        )
        raise

    # Auto-pair transfers only after every current disposition is durable in
    # the transaction. Pair persistence is idempotent under unique leg indexes.
    # Find and pair transfers automatically per common/ledger/readme.md
    try:
        transfer_pairs = await find_transfer_pairs(
            db,
            user_id,
            currency=currency,
            description_scorer=score_description,
            threshold=85,
        )
    except Exception as e:
        logger.error(
            "Failed to auto-pair transfers",
            user_id=str(user_id),
            error=str(e),
        )
        # Non-fatal error - continue with existing matches
        transfer_pairs = []

    if transfer_pairs:
        await persist_transfer_pairs(db, transfer_pairs)
        logger.info(
            "Auto-pairing complete",
            user_id=str(user_id),
            pairs_found=len(transfer_pairs),
        )

    # AC-observability.10.4: emit one business metric per resolved match, labelled by its
    # final disposition (auto_accepted / pending_review / rejected). Low
    # cardinality — the label is the bounded ReconciliationStatus enum value.
    for created_match in matches:
        record_reconciliation_match_outcome(outcome=created_match.status.value)

    return matches


async def sync_reconciliation_match_journal_entry_links(db: AsyncSession, match: ReconciliationMatch) -> None:
    """Synchronize trusted reconciliation anchor links from the compatibility JSONB list."""
    if match.id is None:
        await db.flush()

    target_ids: list[UUID] = []
    seen: set[UUID] = set()
    for raw_entry_id in match.journal_entry_ids or []:
        try:
            entry_id = UUID(str(raw_entry_id))
        except (TypeError, ValueError):
            continue
        if entry_id not in seen:
            seen.add(entry_id)
            target_ids.append(entry_id)

    if target_ids:
        match_user_id = (
            await db.execute(select(AtomicTransaction.user_id).where(AtomicTransaction.id == match.atomic_txn_id))
        ).scalar_one_or_none()
        if match_user_id is None:
            target_ids = []
        else:
            valid_entry_ids = set(
                (
                    await db.execute(
                        select(JournalEntry.id)
                        .where(JournalEntry.id.in_(target_ids))
                        .where(JournalEntry.user_id == match_user_id)
                    )
                ).scalars()
            )
            target_ids = [entry_id for entry_id in target_ids if entry_id in valid_entry_ids]

    existing_ids = set(
        (
            await db.execute(
                select(ReconciliationMatchJournalEntry.journal_entry_id).where(
                    ReconciliationMatchJournalEntry.match_id == match.id
                )
            )
        ).scalars()
    )
    target_set = set(target_ids)

    stale_ids = existing_ids - target_set
    if stale_ids:
        await db.execute(
            delete(ReconciliationMatchJournalEntry).where(
                ReconciliationMatchJournalEntry.match_id == match.id,
                ReconciliationMatchJournalEntry.journal_entry_id.in_(stale_ids),
            )
        )

    for ordinal_entry_id in target_ids:
        if ordinal_entry_id in existing_ids:
            continue
        db.add(
            ReconciliationMatchJournalEntry(
                match_id=match.id,
                journal_entry_id=ordinal_entry_id,
            )
        )
    await db.flush()


def auto_accept(match_score: int, config: ReconciliationConfig) -> bool:
    """Return True if match score meets auto-accept threshold."""
    return match_score >= config.auto_accept
