"""Ledger-dependent entry reads and candidate ordering for matching."""

from __future__ import annotations

from decimal import Decimal

from src.audit import source_type_rank
from src.audit.money import Currency, Money
from src.ledger import AccountType, Direction, JournalEntry, ValidationError, validate_journal_balance
from src.reconciliation.base.config import MatchCandidate


def _candidate_source_rank(candidate: MatchCandidate, entries_by_id: dict[str, JournalEntry]) -> int:
    """Return the highest source_type trust rank among a candidate's entries."""
    return max(
        (source_type_rank(entries_by_id[entry_id].source_type) for entry_id in candidate.journal_entry_ids), default=0
    )


def _candidate_is_better(
    candidate: MatchCandidate,
    best: MatchCandidate | None,
    entries_by_id: dict[str, JournalEntry],
) -> bool:
    """Prefer higher score, then higher source_type trust for deterministic conflict resolution."""
    if best is None:
        return True
    if candidate.score != best.score:
        return candidate.score > best.score

    candidate_rank = _candidate_source_rank(candidate, entries_by_id)
    best_rank = _candidate_source_rank(best, entries_by_id)
    if candidate_rank > best_rank:
        candidate.breakdown["source_type_winner_rank"] = float(candidate_rank)
        candidate.breakdown["source_type_loser_rank"] = float(best_rank)
        return True
    if candidate_rank < best_rank:
        best.breakdown["source_type_winner_rank"] = float(best_rank)
        best.breakdown["source_type_loser_rank"] = float(candidate_rank)
    return False


def entry_total_amount(entry: JournalEntry, *, currency: str) -> Decimal:
    """Return debit magnitude in one explicit transaction currency."""
    target = Currency.of(currency)
    debits = [line.money for line in entry.lines if line.direction == Direction.DEBIT and line.money.currency == target]
    return Money.sum(debits, currency=target).amount


def entry_bank_side_amount(
    entry: JournalEntry,
    transaction_direction: str | None,
    *,
    currency: str,
) -> Decimal:
    """Return the bank/cash-side amount that should match a statement transaction."""
    if not transaction_direction:
        return entry_total_amount(entry, currency=currency)
    direction = transaction_direction.upper()
    bank_line_direction = Direction.DEBIT if direction == "IN" else Direction.CREDIT
    bank_lines = [
        line.money
        for line in entry.lines
        if line.direction == bank_line_direction
        and line.account
        and line.account.type == AccountType.ASSET
        and line.money.currency == Currency.of(currency)
    ]
    if bank_lines:
        return Money.sum(bank_lines, currency=currency).amount
    return entry_total_amount(entry, currency=currency)


def is_entry_balanced(entry: JournalEntry, *, base_currency: str) -> bool:
    """Return True if entry is balanced."""
    try:
        validate_journal_balance(entry.lines, base_currency=base_currency)
    except ValidationError:
        return False
    return True
