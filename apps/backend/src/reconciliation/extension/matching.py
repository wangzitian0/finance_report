"""Reconciliation matching engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, promote_entry_source_type
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import (
    JournalEntry,
    JournalEntryStatus,
    detect_transfer_pattern,
    find_transfer_pairs,
)
from src.llm import ai_semantic_score
from src.observability import get_logger, record_reconciliation_match_outcome
from src.reconciliation.base.config import (  # noqa: F401
    DEFAULT_CONFIG,
    MAX_COMBINATION_CANDIDATES,
    MatchCandidate,
    ReconciliationConfig,
    _candidate_is_better,
    _candidate_source_rank,
    entry_bank_side_amount,
    entry_total_amount,
    is_entry_balanced,
    load_reconciliation_config,
)
from src.reconciliation.base.prompts import build_reconciliation_prompt
from src.reconciliation.base.repository import ReconciliationRepository
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.extension.scoring import (  # noqa: F401
    extract_merchant_tokens,
    is_cross_period,
    normalize_text,
    score_amount,
    score_business_logic,
    score_date,
    score_description,
    score_pattern,
    weighted_total,
)
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
    entries_by_id: dict[str, JournalEntry]
    get_candidates_for_date: Callable[[date], list[JournalEntry]]
    get_cached_pattern_score: Callable[[AtomicTransaction], Awaitable[float]]


def _within_combination_tolerance(
    combined: Decimal, transaction: AtomicTransaction, config: ReconciliationConfig
) -> bool:
    """Whether a multi-entry ``combined`` total is within the matching amount band.

    The shared multi-entry guard, historically inlined verbatim at every 2-/3-entry
    combination site: the per-config band ``max(absolute, percent * |amount|)``
    widened 2x for combinations.

    Kept on raw ``Decimal`` magnitudes (not ``MoneyTolerance``) on purpose: the
    matching pipeline compares same-currency amounts without ever converting, and
    its transactions do not carry a reliable currency, so wrapping in ``Money``
    would add a null-currency failure mode the prior code never had. Adopting
    ``MoneyTolerance`` here waits on reconciliation amounts becoming Money-typed.
    """
    tolerance = max(transaction.amount * config.amount_percent, config.amount_absolute)
    return abs(combined - transaction.amount) <= tolerance * 2


def prune_candidates(
    candidates: list[JournalEntry],
    *,
    txn_date: date,
    target_amount: Decimal,
    limit: int = MAX_COMBINATION_CANDIDATES,
) -> list[JournalEntry]:
    """Reduce candidates before combinational matching to avoid blow-ups.

    Prioritizes:
    1. Exact amount matches (within 1%)
    2. Then by date proximity
    3. Then by absolute amount difference
    """
    if len(candidates) <= limit:
        return candidates

    tolerance = target_amount * Decimal("0.01")  # 1% tolerance for "exact" match

    scored: list[tuple[int, Decimal, int, JournalEntry]] = []
    for entry in candidates:
        amount_diff = abs(entry_total_amount(entry) - target_amount)
        date_diff = abs((txn_date - entry.entry_date).days)
        # Exact match bonus: 0 if within tolerance, 1 otherwise
        exact_match = 0 if amount_diff <= tolerance else 1
        scored.append((exact_match, amount_diff, date_diff, entry))

    # Sort by: exact match first, then amount diff, then date diff
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [entry for _, _, _, entry in scored[:limit]]


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
    entry_amounts = [entry_bank_side_amount(entry, transaction.direction) for entry in entries]
    total_amount = sum(entry_amounts, Decimal("0.00"))
    entry_dates = [entry.entry_date for entry in entries]
    entry_memo = " / ".join([entry.memo for entry in entries]).strip()

    amount_score = score_amount(amount, total_amount, config, is_multi=is_group)
    date_score = max(score_date(transaction.txn_date, d, config) for d in entry_dates)
    description_score = score_description(transaction.description, entry_memo)
    business_score = min(score_business_logic(transaction, entry) for entry in entries) if entries else 0.0

    if history_score is None:
        history_score = await score_pattern(db, transaction, config, user_id=user_id)

    scores = {
        "amount": amount_score,
        "date": date_score,
        "description": description_score,
        "business": business_score,
        "history": history_score,
    }
    if is_group:
        scores["many_to_one_bonus"] = 10.0
        amount_score = min(100.0, amount_score + 5.0)
        scores["amount"] = amount_score

    total = weighted_total(scores, config)

    # EPIC-018 Phase 3: Hybrid scoring for ambiguous matches (60-84 range)
    if config.enable_ai_reconciliation and 60 <= total <= 84:
        primary_entry = entries[0] if entries else None
        if primary_entry:
            date_diff = abs((transaction.txn_date - primary_entry.entry_date).days)
            amount_pct = scores.get("amount", 0.0)
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

    return MatchCandidate(
        journal_entry_ids=[str(entry.id) for entry in entries],
        score=total,
        breakdown=scores,
    )


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


def build_many_to_one_groups(
    transactions: Iterable[AtomicTransaction],
) -> list[list[AtomicTransaction]]:
    """Group transactions that look like batch payments."""
    groups: dict[str, list[AtomicTransaction]] = {}
    keywords = {"batch", "bulk", "settlement", "aggregate"}
    for txn in transactions:
        key = normalize_text(txn.description)
        if not key:
            continue
        if not any(keyword in key for keyword in keywords):
            continue
        group_key = f"{key}:{txn.txn_date.isoformat()}"
        groups.setdefault(group_key, []).append(txn)
    return [group for group in groups.values() if len(group) > 1]


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
    ``extraction.register_transfer_exclusions_provider`` at startup
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


def _find_transfer_candidates(
    pending_txns: list[AtomicTransaction],
    atomic_txns: list[JournalEntry],
    pattern_scores: dict[str, float],
    config: ReconciliationConfig,
) -> list[tuple[AtomicTransaction, MatchCandidate, AtomicTransaction | None]]:
    """Identify transfer-pattern transactions and return scored candidates.

    Pure scoring function: no DB access. Each result is
    (bank_txn, candidate_with_score_100, paired_txn_or_None).
    The paired_txn is always None here because actual pairing (find_transfer_pairs)
    happens after all phases in execute_matching.
    """
    results: list[tuple[AtomicTransaction, MatchCandidate, AtomicTransaction | None]] = []
    for txn in pending_txns:
        if not detect_transfer_pattern(txn.description):
            continue
        direction_key = "transfer_out" if txn.direction == "OUT" else "transfer_in"
        candidate = MatchCandidate(
            journal_entry_ids=[],  # Will be populated by orchestrator after DB write
            score=100,
            breakdown={direction_key: 100.0},
        )
        results.append((txn, candidate, None))
    return results


def _find_many_to_one_candidates(
    pending_txns: list[AtomicTransaction],
    atomic_txns: list[JournalEntry],
    pattern_scores: dict[str, float],
    config: ReconciliationConfig,
) -> list[tuple[AtomicTransaction, MatchCandidate]]:
    """Find many-to-one match candidates by grouping batch transactions.

    Pure scoring function: no DB access. Uses pre-computed pattern_scores
    for historical matching. Returns (representative_txn, best_candidate)
    for each group that scores above pending_review threshold.
    """
    date_start = min(e.entry_date for e in atomic_txns) if atomic_txns else None
    date_end = max(e.entry_date for e in atomic_txns) if atomic_txns else None

    def get_candidates_for_date(txn_date: date) -> list[JournalEntry]:
        if date_start is None or date_end is None:
            return []
        d_start = txn_date - timedelta(days=config.date_days)
        d_end = txn_date + timedelta(days=config.date_days)
        return [c for c in atomic_txns if d_start <= c.entry_date <= d_end]

    results: list[tuple[AtomicTransaction, MatchCandidate]] = []
    groups = build_many_to_one_groups(pending_txns)
    for group in groups:
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

        tokens = extract_merchant_tokens(group[0].description)
        history_score = pattern_scores.get(tokens[0], 0.0) if tokens else 0.0

        best_candidate: MatchCandidate | None = None
        for entry in candidates:
            if not is_entry_balanced(entry):
                continue

            # Inline scoring using pure functions (no DB)
            txn_amount = group_total
            entry_amount = entry_bank_side_amount(entry, group[0].direction)
            amount_score = score_amount(txn_amount, entry_amount, config, is_multi=True)
            date_score = score_date(group[0].txn_date, entry.entry_date, config)
            description_score = score_description(group[0].description, entry.memo)
            business_score = score_business_logic(group[0], entry)

            scores: dict[str, float] = {
                "amount": amount_score,
                "date": date_score,
                "description": description_score,
                "business": business_score,
                "history": history_score,
                "many_to_one_bonus": 10.0,
            }
            # Apply many-to-one amount bonus
            scores["amount"] = min(100.0, scores["amount"] + 5.0)
            total = weighted_total(scores, config)

            candidate = MatchCandidate(
                journal_entry_ids=[str(entry.id)],
                score=total,
                breakdown={**scores, "group_total": str(group_total)},
            )
            if candidate.score >= config.pending_review and (
                best_candidate is None or candidate.score > best_candidate.score
            ):
                best_candidate = candidate

        if best_candidate:
            results.append((group[0], best_candidate))
    return results


def _find_normal_candidates(
    pending_txns: list[AtomicTransaction],
    atomic_txns: list[JournalEntry],
    pattern_scores: dict[str, float],
    config: ReconciliationConfig,
) -> list[tuple[AtomicTransaction, MatchCandidate]]:
    """Find normal 1:1 and 1:N match candidates.

    Pure scoring function: no DB access. Uses pre-computed pattern_scores.
    Tries single entry, 2-entry, and 3-entry combinations.
    Returns (bank_txn, best_candidate) for each transaction that scores
    above pending_review threshold.
    """
    date_start = min(e.entry_date for e in atomic_txns) if atomic_txns else None
    date_end = max(e.entry_date for e in atomic_txns) if atomic_txns else None

    def get_candidates_for_date(txn_date: date) -> list[JournalEntry]:
        if date_start is None or date_end is None:
            return []
        d_start = txn_date - timedelta(days=config.date_days)
        d_end = txn_date + timedelta(days=config.date_days)
        return [c for c in atomic_txns if d_start <= c.entry_date <= d_end]

    def _score_entries(
        txn: AtomicTransaction,
        entries: list[JournalEntry],
        history_score: float,
        is_multi: bool = False,
    ) -> MatchCandidate:
        entry_amounts = [entry_bank_side_amount(e, txn.direction) for e in entries]
        total_amount = sum(entry_amounts, Decimal("0.00"))
        entry_dates = [e.entry_date for e in entries]
        entry_memo = " / ".join([e.memo for e in entries]).strip()

        amount_s = score_amount(txn.amount, total_amount, config, is_multi=is_multi)
        date_s = max(score_date(txn.txn_date, d, config) for d in entry_dates)
        description_s = score_description(txn.description, entry_memo)
        business_s = min(score_business_logic(txn, e) for e in entries) if entries else 0.0

        scores: dict[str, float] = {
            "amount": amount_s,
            "date": date_s,
            "description": description_s,
            "business": business_s,
            "history": history_score,
        }
        total = weighted_total(scores, config)
        return MatchCandidate(
            journal_entry_ids=[str(e.id) for e in entries],
            score=total,
            breakdown=scores,
        )

    results: list[tuple[AtomicTransaction, MatchCandidate]] = []
    for txn in pending_txns:
        candidates = get_candidates_for_date(txn.txn_date)
        if not candidates:
            continue
        candidates = prune_candidates(
            candidates,
            txn_date=txn.txn_date,
            target_amount=txn.amount,
        )

        tokens = extract_merchant_tokens(txn.description)
        history_score = pattern_scores.get(tokens[0], 0.0) if tokens else 0.0

        best_match: MatchCandidate | None = None

        # Single entry matching
        for entry in candidates:
            if not is_entry_balanced(entry):
                continue
            candidate = _score_entries(txn, [entry], history_score)
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        # Two-entry combinations
        for entry_a, entry_b in combinations(candidates, 2):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b)):
                continue
            combined = entry_bank_side_amount(entry_a, txn.direction) + entry_bank_side_amount(entry_b, txn.direction)
            if not _within_combination_tolerance(combined, txn, config):
                continue
            candidate = _score_entries(txn, [entry_a, entry_b], history_score, is_multi=True)
            candidate.breakdown["multi_entry"] = 1
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        # Three-entry combinations
        for entry_a, entry_b, entry_c in combinations(candidates, 3):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b) and is_entry_balanced(entry_c)):
                continue
            combined = (
                entry_bank_side_amount(entry_a, txn.direction)
                + entry_bank_side_amount(entry_b, txn.direction)
                + entry_bank_side_amount(entry_c, txn.direction)
            )
            if not _within_combination_tolerance(combined, txn, config):
                continue
            candidate = _score_entries(txn, [entry_a, entry_b, entry_c], history_score, is_multi=True)
            candidate.breakdown["multi_entry"] = 2
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        if best_match and best_match.score >= config.pending_review:
            results.append((txn, best_match))
    return results


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

    # Phase 1: Transfer Detection (BEFORE normal matching)
    matches.extend(
        await run_transfer_detection_phase(
            db,
            transactions=transactions,
            matched_txn_ids=matched_txn_ids,
            repository=repo,
            user_id=user_id,
            currency=currency,
        )
    )

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

    # Phase 3: Auto-Pair Transfers (AFTER all matching complete)
    # Find and pair transfers automatically per common/ledger/readme.md
    try:
        transfer_pairs = await find_transfer_pairs(
            db,
            user_id,
            currency=currency,
            description_scorer=score_description,
            threshold=85,
        )
        if transfer_pairs:
            logger.info(
                "Auto-pairing complete",
                user_id=str(user_id),
                pairs_found=len(transfer_pairs),
            )
    except Exception as e:
        logger.error(
            "Failed to auto-pair transfers",
            user_id=str(user_id),
            error=str(e),
        )
        # Non-fatal error - continue with existing matches

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
