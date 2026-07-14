"""Behaviour-preserving guard for the #1253 ROI #4 value-type adoption.

Pins the *exact* prior behaviour of reconciliation's multi-entry tolerance
check so the refactor (4 verbatim copies -> one shared helper) cannot silently
drift.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.reconciliation import _within_combination_tolerance
from src.reconciliation.base.config import DEFAULT_CONFIG


class _Txn:
    """Minimal stand-in for the AtomicTransaction fields the helper reads."""

    def __init__(self, amount: Decimal, currency: str = "USD") -> None:
        self.amount = amount
        self.currency = currency


def _old_within_tolerance(combined: Decimal, amount: Decimal, config) -> bool:
    """The pre-refactor inline formula, kept here as the oracle."""
    tolerance = max(amount * config.amount_percent, config.amount_absolute)
    return not (abs(combined - amount) > tolerance * 2)


@pytest.mark.parametrize(
    "combined, amount",
    [
        (Decimal("100.00"), Decimal("100.00")),  # exact
        (Decimal("100.50"), Decimal("100.00")),  # outside band
        (Decimal("100.21"), Decimal("100.00")),  # just outside (percent leg)
        (Decimal("100.20"), Decimal("100.00")),  # exactly on the doubled boundary
        (Decimal("99.79"), Decimal("100.00")),  # below boundary
        (Decimal("10000.00"), Decimal("9900.00")),  # large percent leg dominates
        (Decimal("0.30"), Decimal("0.10")),  # absolute leg dominates
        (Decimal("0.31"), Decimal("0.10")),  # absolute leg, just outside
    ],
)
def test_combination_tolerance_matches_legacy_formula(combined: Decimal, amount: Decimal) -> None:
    """AC4.2.3: multi-entry tolerance boundary == the old max(amount*pct, abs)*2 comparison."""
    txn = _Txn(amount)
    assert _within_combination_tolerance(combined, txn, DEFAULT_CONFIG) == _old_within_tolerance(
        combined, amount, DEFAULT_CONFIG
    )
