"""Reconciliation-owned review-score presentation tests."""

import pytest

from src.reconciliation import derive_reconciliation_score_tier


@pytest.mark.parametrize(
    "score,expected",
    [
        (None, "LOW"),
        (59, "LOW"),
        (60, "MEDIUM"),
        (84, "MEDIUM"),
        (85, "HIGH"),
        (100, "HIGH"),
    ],
)
def test_ac4_9_4_derive_reconciliation_score_tier(score, expected):
    """AC-reconciliation.bank-side-amount.5."""
    assert derive_reconciliation_score_tier(score) == expected
