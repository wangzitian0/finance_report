"""Deterministic candidate policy shared by live matching and its audit.

Ledger reads belong in this extension, not in the pure configuration layer.
History and optional AI I/O remain in the live matching adapter.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import JournalEntry, detect_transfer_pattern
from src.reconciliation.base.config import MAX_COMBINATION_CANDIDATES, MatchCandidate, ReconciliationConfig
from src.reconciliation.extension.entry_reads import (
    _candidate_is_better,
    entry_bank_side_amount,
    entry_total_amount,
    is_entry_balanced,
)
from src.reconciliation.extension.scoring import (
    extract_merchant_tokens,
    normalize_text,
    score_amount,
    score_business_logic,
    score_date,
    score_description,
    weighted_total,
)


def _within_combination_tolerance(
    combined: Decimal, transaction: AtomicTransaction, config: ReconciliationConfig
) -> bool:
    """Whether a multi-entry ``combined`` total is within the matching amount band.

    The shared multi-entry guard, historically inlined verbatim at every 2-/3-entry
    combination site: the per-config band ``max(absolute, percent * |amount|)``
    widened 2x for combinations.

    Kept on raw ``Decimal`` magnitudes (not ``MoneyTolerance``) because callers
    first derive ``combined`` from lines filtered by the non-null transaction
    currency. The helper compares magnitudes only and must never receive a
    cross-currency nominal sum.
    """
    tolerance = max(transaction.amount * config.amount_percent, config.amount_absolute)
    return abs(combined - transaction.amount) <= tolerance * 2


def prune_candidates(
    candidates: list[JournalEntry],
    *,
    txn_date: date,
    target_amount: Decimal,
    currency: str,
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
        amount_diff = abs(entry_total_amount(entry, currency=currency) - target_amount)
        date_diff = abs((txn_date - entry.entry_date).days)
        # Exact match bonus: 0 if within tolerance, 1 otherwise
        exact_match = 0 if amount_diff <= tolerance else 1
        scored.append((exact_match, amount_diff, date_diff, entry))

    # Sort by: exact match first, then amount diff, then date diff
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [entry for _, _, _, entry in scored[:limit]]


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
        group_key = f"{key}:{txn.txn_date.isoformat()}:{txn.direction}:{txn.currency}"
        groups.setdefault(group_key, []).append(txn)
    return [group for group in groups.values() if len(group) > 1]


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


def _score_rule_candidate(
    transaction: AtomicTransaction,
    entries: list[JournalEntry],
    config: ReconciliationConfig,
    *,
    amount: Decimal,
    is_group: bool,
    history_score: float,
) -> MatchCandidate:
    """Score loaded evidence without performing history or provider I/O."""
    total_amount = sum(
        (entry_bank_side_amount(entry, transaction.direction, currency=transaction.currency) for entry in entries),
        Decimal("0.00"),
    )
    scores = {
        "amount": score_amount(amount, total_amount, config, is_multi=is_group or len(entries) > 1),
        "date": max(score_date(transaction.txn_date, entry.entry_date, config) for entry in entries),
        "description": score_description(transaction.description, " / ".join(entry.memo for entry in entries).strip()),
        "business": min(score_business_logic(transaction, entry) for entry in entries) if entries else 0.0,
        "history": history_score,
    }
    if is_group:
        scores["many_to_one_bonus"] = 10.0
        scores["amount"] = min(100.0, scores["amount"] + 5.0)
    return MatchCandidate(
        journal_entry_ids=[str(entry.id) for entry in entries],
        score=weighted_total(scores, config),
        breakdown=dict(scores),
    )


def _normal_entry_combinations(
    transaction: AtomicTransaction,
    candidates: list[JournalEntry],
    config: ReconciliationConfig,
    *,
    base_currency: str,
) -> Iterator[list[JournalEntry]]:
    """Enumerate balanced singles and amount-eligible pairs/triples once."""
    balanced = [entry for entry in candidates if is_entry_balanced(entry, base_currency=base_currency)]
    for size in (1, 2, 3):
        for entries in combinations(balanced, size):
            if size > 1:
                combined = sum(
                    (
                        entry_bank_side_amount(entry, transaction.direction, currency=transaction.currency)
                        for entry in entries
                    ),
                    Decimal("0.00"),
                )
                if not _within_combination_tolerance(combined, transaction, config):
                    continue
            yield list(entries)


def _date_candidates(entries: list[JournalEntry], txn_date: date, config: ReconciliationConfig) -> list[JournalEntry]:
    start = txn_date - timedelta(days=config.date_days)
    end = txn_date + timedelta(days=config.date_days)
    return [entry for entry in entries if start <= entry.entry_date <= end]


def _history_score(transaction: AtomicTransaction, pattern_scores: dict[str, float]) -> float:
    tokens = extract_merchant_tokens(transaction.description)
    return pattern_scores.get(tokens[0], 0.0) if tokens else 0.0


def _find_many_to_one_candidates(
    pending_txns: list[AtomicTransaction],
    atomic_txns: list[JournalEntry],
    pattern_scores: dict[str, float],
    config: ReconciliationConfig,
    *,
    base_currency: str,
) -> list[tuple[AtomicTransaction, MatchCandidate]]:
    """Evaluate batch groups with the live rule score and source ordering."""
    results: list[tuple[AtomicTransaction, MatchCandidate]] = []
    entries_by_id = {str(entry.id): entry for entry in atomic_txns}
    for group in build_many_to_one_groups(pending_txns):
        transaction = group[0]
        amount = sum((txn.amount for txn in group), Decimal("0.00"))
        txn_date = max(txn.txn_date for txn in group)
        candidates = prune_candidates(
            _date_candidates(atomic_txns, txn_date, config),
            txn_date=txn_date,
            target_amount=amount,
            currency=transaction.currency,
        )
        best = None
        for entry in candidates:
            if not is_entry_balanced(entry, base_currency=base_currency):
                continue
            candidate = _score_rule_candidate(
                transaction,
                [entry],
                config,
                amount=amount,
                is_group=True,
                history_score=_history_score(transaction, pattern_scores),
            )
            candidate.breakdown["group_total"] = str(amount)
            if candidate.score >= config.pending_review and _candidate_is_better(candidate, best, entries_by_id):
                best = candidate
        if best:
            results.append((transaction, best))
    return results


def _find_normal_candidates(
    pending_txns: list[AtomicTransaction],
    atomic_txns: list[JournalEntry],
    pattern_scores: dict[str, float],
    config: ReconciliationConfig,
    *,
    base_currency: str,
) -> list[tuple[AtomicTransaction, MatchCandidate]]:
    """Evaluate journal evidence with the live enumeration, rules and ordering."""
    results: list[tuple[AtomicTransaction, MatchCandidate]] = []
    entries_by_id = {str(entry.id): entry for entry in atomic_txns}
    for transaction in pending_txns:
        candidates = prune_candidates(
            _date_candidates(atomic_txns, transaction.txn_date, config),
            txn_date=transaction.txn_date,
            target_amount=transaction.amount,
            currency=transaction.currency,
        )
        best = None
        for entries in _normal_entry_combinations(transaction, candidates, config, base_currency=base_currency):
            candidate = _score_rule_candidate(
                transaction,
                entries,
                config,
                amount=transaction.amount,
                is_group=False,
                history_score=_history_score(transaction, pattern_scores),
            )
            if len(entries) > 1:
                candidate.breakdown["multi_entry"] = len(entries) - 1
            if _candidate_is_better(candidate, best, entries_by_id):
                best = candidate
        if best and best.score >= config.pending_review:
            results.append((transaction, best))
    return results
