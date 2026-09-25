"""Pure calculation engine for reconciliation scoring and similarity matching."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Literal

from src.reconciliation.base.config import ReconciliationConfig

ReconciliationConfidenceTier = Literal["HIGH", "MEDIUM", "LOW"]


def derive_reconciliation_score_tier(score: int | None) -> ReconciliationConfidenceTier:
    """Map one reconciliation match score to its review-queue presentation tier."""
    if score is None or score < 60:
        return "LOW"
    if score < 85:
        return "MEDIUM"
    return "HIGH"


def normalize_text(value: str) -> str:
    """Normalize text for similarity comparison."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def score_description(a: str | None, b: str | None) -> float:
    """Score description similarity (0-100)."""
    if not a or not b:
        return 0.0
    norm_a = normalize_text(a)
    norm_b = normalize_text(b)
    if not norm_a or not norm_b:
        return 0.0
    ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    token_score = len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a | tokens_b else 0
    return round(100 * (0.6 * ratio + 0.4 * token_score), 2)


def score_amount(
    txn_amount: Decimal,
    entry_amount: Decimal,
    config: ReconciliationConfig,
    is_multi: bool = False,
) -> float:
    """Score amount match (0-100)."""
    diff = abs(txn_amount - entry_amount)
    if diff <= Decimal("0.01"):
        return 100.0

    tolerance = max(txn_amount * config.amount_percent, config.amount_absolute)
    if diff <= tolerance:
        return 90.0
    if diff <= Decimal("5.00"):
        return 70.0
    if is_multi and diff <= tolerance * 2:
        return 70.0
    if txn_amount == Decimal("0"):
        return 0.0

    ratio = max(Decimal("0"), Decimal("100") - (diff / txn_amount) * Decimal("100"))
    return float(round(ratio, 2))


def is_cross_period(txn_date: date, entry_date: date, max_days: int) -> bool:
    """Detect cross-period matching scenarios."""
    if txn_date.month == entry_date.month:
        return False
    return abs((txn_date - entry_date).days) <= max_days


def score_date(txn_date: date, entry_date: date, config: ReconciliationConfig) -> float:
    """Score date proximity (0-100)."""
    diff_days = abs((txn_date - entry_date).days)
    if diff_days == 0:
        return 100.0
    if diff_days <= 3:
        return 90.0

    # Check if within acceptable date window
    if diff_days <= config.date_days:
        # Cross-period matching gets a slight bonus (e.g., Friday txn -> Monday entry)
        if is_cross_period(txn_date, entry_date, max_days=config.date_days):
            return 75.0
        return 70.0

    # Beyond acceptable window - rapidly decreasing score
    return float(max(0, 100 - diff_days * 10))


def extract_merchant_tokens(description: str) -> list[str]:
    """Extract meaningful merchant tokens from transaction description.

    Improved extraction that takes up to 3 significant words, skipping
    common prefixes like transaction codes, dates, and generic terms.
    """
    skip_patterns = {
        "ref",
        "txn",
        "trn",
        "pos",
        "atm",
        "eft",
        "ibk",
        "ibt",
        "payment",
        "transfer",
        "debit",
        "credit",
        "card",
        "visa",
        "mastercard",
    }
    words = normalize_text(description).split()
    tokens = []
    for word in words:
        if len(word) < 3:
            continue
        if re.match(r"^\d+$", word):
            continue
        if word in skip_patterns:
            continue
        tokens.append(word)
        if len(tokens) >= 3:
            break
    return tokens


def weighted_total(scores: dict[str, float], config: ReconciliationConfig) -> int:
    """Compute weighted total score."""
    total = (
        Decimal(str(scores["amount"])) * config.weight_amount
        + Decimal(str(scores["date"])) * config.weight_date
        + Decimal(str(scores["description"])) * config.weight_description
        + Decimal(str(scores["business"])) * config.weight_business
        + Decimal(str(scores["history"])) * config.weight_history
    )
    return int(round(total, 0))
