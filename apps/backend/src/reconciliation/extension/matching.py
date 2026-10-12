"""Reconciliation matching engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
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
        await sync_reconciliation_matches_journal_entry_links_batch(
            db,
            matches,
            user_id=user_id,
            known_candidates=entries_by_id,
        )
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


async def sync_reconciliation_matches_journal_entry_links_batch(
    db: AsyncSession,
    matches: Sequence[ReconciliationMatch],
    *,
    user_id: UUID | None = None,
    known_candidates: Mapping[UUID, JournalEntry] | Iterable[JournalEntry | UUID | str] | None = None,
) -> None:
    """Batch synchronize trusted reconciliation anchor links from compatibility JSONB lists.

    Eliminates per-match SELECT queries and per-item flush roundtrips.
    """
    if not matches:
        return

    # Ensure matches have IDs
    unflushed_matches = [m for m in matches if m.id is None]
    if unflushed_matches:
        await db.flush()

    target_ids_by_match: dict[ReconciliationMatch, list[UUID]] = {}
    all_target_ids: set[UUID] = set()
    for match in matches:
        match_target_ids: list[UUID] = []
        seen: set[UUID] = set()
        for raw_entry_id in match.journal_entry_ids or []:
            try:
                entry_id = UUID(str(raw_entry_id))
            except (TypeError, ValueError):
                continue
            if entry_id not in seen:
                seen.add(entry_id)
                match_target_ids.append(entry_id)
        target_ids_by_match[match] = match_target_ids
        all_target_ids.update(match_target_ids)

    if all_target_ids:
        # Resolve user_id for matches if not provided explicitly
        match_user_ids: dict[ReconciliationMatch, UUID | None] = {}
        if user_id is not None:
            match_user_ids = {match: user_id for match in matches}
        else:
            txn_ids = [match.atomic_txn_id for match in matches if match.atomic_txn_id is not None]
            if txn_ids:
                txn_rows = (
                    await db.execute(
                        select(AtomicTransaction.id, AtomicTransaction.user_id).where(AtomicTransaction.id.in_(txn_ids))
                    )
                ).all()
                txn_user_map = {row[0]: row[1] for row in txn_rows}
                match_user_ids = {match: txn_user_map.get(match.atomic_txn_id) for match in matches}
            else:
                match_user_ids = {match: None for match in matches}

        # Build known valid entry IDs from known_candidates
        known_valid_by_user: dict[UUID, set[UUID]] = {}
        if known_candidates is not None:
            if isinstance(known_candidates, Mapping):
                for candidate in known_candidates.values():
                    if isinstance(candidate, JournalEntry) and candidate.user_id is not None:
                        known_valid_by_user.setdefault(candidate.user_id, set()).add(candidate.id)
            elif isinstance(known_candidates, Iterable):
                for item in known_candidates:
                    if isinstance(item, JournalEntry) and item.user_id is not None:
                        known_valid_by_user.setdefault(item.user_id, set()).add(item.id)
                    elif isinstance(item, UUID) and user_id is not None:
                        known_valid_by_user.setdefault(user_id, set()).add(item)
                    elif isinstance(item, str) and user_id is not None:
                        try:
                            known_valid_by_user.setdefault(user_id, set()).add(UUID(item))
                        except (TypeError, ValueError):
                            pass

        # Check which target IDs need database resolution
        unresolved_target_ids: set[UUID] = set()
        for match, t_ids in target_ids_by_match.items():
            m_uid = match_user_ids.get(match)
            if m_uid is not None:
                known_for_user = known_valid_by_user.get(m_uid, set())
                for eid in t_ids:
                    if eid not in known_for_user:
                        unresolved_target_ids.add(eid)

        if unresolved_target_ids:
            query_result = (
                await db.execute(
                    select(JournalEntry.id, JournalEntry.user_id).where(JournalEntry.id.in_(unresolved_target_ids))
                )
            ).all()
            for eid, e_uid in query_result:
                known_valid_by_user.setdefault(e_uid, set()).add(eid)

        # Filter target_ids per match to only include valid entries for that user
        for match in matches:
            m_uid = match_user_ids.get(match)
            if m_uid is None:
                target_ids_by_match[match] = []
            else:
                valid_entries = known_valid_by_user.get(m_uid, set())
                target_ids_by_match[match] = [eid for eid in target_ids_by_match[match] if eid in valid_entries]

    # Resolve existing links in batch
    match_ids = [match.id for match in matches if match.id is not None]
    existing_by_match: dict[UUID, set[UUID]] = {}
    if match_ids:
        existing_rows = (
            await db.execute(
                select(
                    ReconciliationMatchJournalEntry.match_id, ReconciliationMatchJournalEntry.journal_entry_id
                ).where(ReconciliationMatchJournalEntry.match_id.in_(match_ids))
            )
        ).all()
        for m_id, j_id in existing_rows:
            existing_by_match.setdefault(m_id, set()).add(j_id)

    # Reconcile links
    for match in matches:
        if match.id is None:
            continue
        existing_ids = existing_by_match.get(match.id, set())
        target_ids = target_ids_by_match.get(match, [])
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


async def sync_reconciliation_match_journal_entry_links(db: AsyncSession, match: ReconciliationMatch) -> None:
    """Synchronize trusted reconciliation anchor links from the compatibility JSONB list."""
    await sync_reconciliation_matches_journal_entry_links_batch(db, [match])


def auto_accept(match_score: int, config: ReconciliationConfig) -> bool:
    """Return True if match score meets auto-accept threshold."""
    return match_score >= config.auto_accept
