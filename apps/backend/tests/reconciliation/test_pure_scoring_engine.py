"""AC-reconciliation.review-queue.1: Pure domain unit tests for reconciliation scoring engine."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from src.reconciliation.base.config import DEFAULT_CONFIG
from src.reconciliation.base.scoring_engine import (
    derive_reconciliation_score_tier,
    extract_merchant_tokens,
    is_cross_period,
    normalize_text,
    score_amount,
    score_date,
    score_description,
)

pytestmark = pytest.mark.no_db


def test_score_amount_exact_and_tolerances():
    """AC-reconciliation.review-queue.1: Exact amounts score 100, within tolerance 90, distant amounts lower."""
    config = replace(
        DEFAULT_CONFIG,
        amount_percent=Decimal("0.02"),
        amount_absolute=Decimal("1.00"),
    )

    # Exact match (diff <= 0.01)
    assert score_amount(Decimal("100.00"), Decimal("100.00"), config) == 100.0
    assert score_amount(Decimal("100.00"), Decimal("100.01"), config) == 100.0

    # Within tolerance ($100 * 2% = $2.00)
    assert score_amount(Decimal("100.00"), Decimal("101.50"), config) == 90.0

    # Within $5.00 diff
    assert score_amount(Decimal("100.00"), Decimal("104.00"), config) == 70.0

    # Large difference
    assert score_amount(Decimal("100.00"), Decimal("200.00"), config) == 0.0


def test_score_date_tiers_and_cross_period():
    """AC-reconciliation.review-queue.1: Date tiers score 100 same day, 90 near, 75 cross-period bonus."""
    config = replace(DEFAULT_CONFIG, date_days=7)

    # Same day
    d1 = date(2025, 4, 15)
    assert score_date(d1, d1, config) == 100.0

    # Within 3 days (e.g. 2 days diff)
    assert score_date(d1, date(2025, 4, 17), config) == 90.0

    # Same month within 7 days (e.g. 6 days diff)
    assert score_date(d1, date(2025, 4, 21), config) == 70.0

    # Cross-month between 4 and 7 days (e.g. 2025-04-27 to 2025-05-02 is 5 days)
    apr_27 = date(2025, 4, 27)
    may_02 = date(2025, 5, 2)
    assert is_cross_period(apr_27, may_02, max_days=7) is True
    assert score_date(apr_27, may_02, config) == 75.0


def test_text_normalization_and_merchant_token_extraction():
    """AC-reconciliation.review-queue.1: Text normalization and merchant token extraction filter noise."""
    assert normalize_text("  GRAB* TAXI / TRIP #123  ") == "grab taxi trip 123"

    tokens = extract_merchant_tokens("POS DEBIT 987654 NETFLIX COM SINGAPORE")
    # "pos", "debit" are skip patterns, numbers skipped, "netflix" and "singapore" extracted
    assert "netflix" in tokens
    assert "singapore" in tokens
    assert "pos" not in tokens
    assert "debit" not in tokens


def test_derive_reconciliation_score_tier():
    """AC-reconciliation.review-queue.1: Tier boundaries partition into HIGH, MEDIUM, LOW."""
    assert derive_reconciliation_score_tier(None) == "LOW"
    assert derive_reconciliation_score_tier(59) == "LOW"
    assert derive_reconciliation_score_tier(60) == "MEDIUM"
    assert derive_reconciliation_score_tier(84) == "MEDIUM"
    assert derive_reconciliation_score_tier(85) == "HIGH"
    assert derive_reconciliation_score_tier(100) == "HIGH"


def test_score_description():
    """AC-reconciliation.review-queue.1: Fuzzy description matching with token overlap."""
    assert score_description(None, "Grab Taxi") == 0.0
    assert score_description("Grab Taxi", None) == 0.0
    assert score_description("Grab Taxi Singapore", "Grab Taxi Singapore") == 100.0
    assert score_description("Grab Taxi", "Grab Car") > 40.0
