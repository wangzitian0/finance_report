"""Reconciliation configuration values and candidate records; no runtime I/O."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.audit import RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE


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
    # Scores are 0-100 percentages; exact money diagnostics such as
    # ``group_total`` are serialized as strings, never floats.
    breakdown: dict[str, float | str]


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
