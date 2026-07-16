"""Reconciliation config, match-candidate types, and entry helpers (split from reconciliation.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from src.audit import (
    RECONCILIATION_AUTO_ACCEPT_SCORE,
    RECONCILIATION_REVIEW_SCORE,
    source_type_rank,
)
from src.audit.money import Money
from src.ledger import AccountType, Direction, JournalEntry, ValidationError, validate_journal_balance
from src.observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReconciliationConfig:
    """Runtime configuration for reconciliation scoring."""

    weight_amount: Decimal
    weight_date: Decimal
    weight_description: Decimal
    weight_business: Decimal
    weight_history: Decimal
    auto_accept: int
    pending_review: int
    amount_percent: Decimal
    amount_absolute: Decimal
    date_days: int
    enable_ai_reconciliation: bool = False


@dataclass
class MatchCandidate:
    """Candidate match result."""

    journal_entry_ids: list[str]
    score: int
    # Score components are 0-100 percentages, not monetary values.
    # Float is acceptable per AGENTS.md which requires Decimal only for money.
    breakdown: dict[str, float]


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


def entry_total_amount(entry: JournalEntry) -> Decimal:
    """Return total debit amount for matching."""
    debits = [line.money for line in entry.lines if line.direction == Direction.DEBIT]
    return Money.sum(debits).amount if debits else Decimal("0.00")


def entry_bank_side_amount(entry: JournalEntry, transaction_direction: str | None) -> Decimal:
    """Return the bank/cash-side amount that should match a statement transaction."""
    if not transaction_direction:
        return entry_total_amount(entry)
    direction = transaction_direction.upper()
    bank_line_direction = Direction.DEBIT if direction == "IN" else Direction.CREDIT
    bank_lines = [
        line.money
        for line in entry.lines
        if line.direction == bank_line_direction and line.account and line.account.type == AccountType.ASSET
    ]
    if bank_lines:
        return Money.sum(bank_lines).amount
    return entry_total_amount(entry)


def is_entry_balanced(entry: JournalEntry) -> bool:
    """Return True if entry is balanced."""
    try:
        validate_journal_balance(entry.lines)
    except ValidationError:
        return False
    return True


DEFAULT_CONFIG = ReconciliationConfig(
    weight_amount=Decimal("0.40"),
    weight_date=Decimal("0.25"),
    weight_description=Decimal("0.20"),
    weight_business=Decimal("0.10"),
    weight_history=Decimal("0.05"),
    auto_accept=RECONCILIATION_AUTO_ACCEPT_SCORE,
    pending_review=RECONCILIATION_REVIEW_SCORE,
    amount_percent=Decimal("0.005"),
    amount_absolute=Decimal("0.10"),
    date_days=7,
)

MAX_COMBINATION_CANDIDATES = 30

_config_cache: ReconciliationConfig | None = None


def load_reconciliation_config(force_reload: bool = False) -> ReconciliationConfig:
    """Load reconciliation configuration from YAML if available.

    Caches the result to avoid repeated disk I/O.
    """
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache

    config = DEFAULT_CONFIG
    config_path = Path(__file__).resolve().parents[2] / "config" / "reconciliation.yaml"

    if config_path.exists():
        _yaml: ModuleType | None
        try:
            import yaml as _yaml
        except ImportError:
            _yaml = None

        if _yaml is not None:
            try:
                raw = _yaml.safe_load(config_path.read_text()) or {}
                scoring = raw.get("scoring", {})
                weights = scoring.get("weights", {})
                thresholds = scoring.get("thresholds", {})
                tolerances = scoring.get("tolerances", {})

                config = ReconciliationConfig(
                    weight_amount=Decimal(str(weights.get("amount", config.weight_amount))),
                    weight_date=Decimal(str(weights.get("date", config.weight_date))),
                    weight_description=Decimal(str(weights.get("description", config.weight_description))),
                    weight_business=Decimal(str(weights.get("business", config.weight_business))),
                    weight_history=Decimal(str(weights.get("history", config.weight_history))),
                    auto_accept=int(thresholds.get("auto_accept", config.auto_accept)),
                    pending_review=int(thresholds.get("pending_review", config.pending_review)),
                    amount_percent=Decimal(str(tolerances.get("amount_percent", config.amount_percent))),
                    amount_absolute=Decimal(str(tolerances.get("amount_absolute", config.amount_absolute))),
                    date_days=int(tolerances.get("date_days", config.date_days)),
                    enable_ai_reconciliation=bool(
                        scoring.get(
                            "enable_ai_reconciliation",
                            config.enable_ai_reconciliation,
                        )
                    ),
                )
            except Exception as e:
                logger.warning(
                    "Failed to load reconciliation config - using defaults",
                    config_path=str(config_path),
                    error=str(e),
                    error_type=type(e).__name__,
                )

    auto_accept_env = os.getenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD")
    pending_review_env = os.getenv("RECONCILIATION_REVIEW_THRESHOLD")
    enable_ai_env = os.getenv("ENABLE_AI_RECONCILIATION")
    if auto_accept_env:
        config = replace(config, auto_accept=int(auto_accept_env))
    if pending_review_env:
        config = replace(config, pending_review=int(pending_review_env))
    if enable_ai_env is not None:
        config = replace(
            config,
            enable_ai_reconciliation=enable_ai_env.lower() in {"1", "true", "yes", "on"},
        )

    _config_cache = config
    return config
