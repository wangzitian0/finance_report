"""Behaviour-preserving guards for the #1253 ROI #2/#4/#6 value-type adoptions.

These pin the *exact* prior behaviour of three call-site simplifications so the
refactor cannot silently drift:

- #2 reporting aggregations now call the shared ``_core._line_total`` verb;
- #4 reconciliation's 4 verbatim multi-entry tolerance copies now share one helper;
- #6 allocation now uses ``Ratio.fraction_or_zero`` instead of a ``> 0`` guard.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.services.allocation import _build_allocation
from src.services.reconciliation import _within_combination_tolerance
from src.services.reconciliation_config import DEFAULT_CONFIG
from src.services.reporting._core import _line_total


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


def test_build_allocation_zero_total_yields_zero_percent() -> None:
    """AC17.4.4: an all-zero portfolio yields 0% per category (no ZeroDivision, no raise)."""
    enriched = [(object(), Decimal("0")), (object(), Decimal("0"))]
    breakdowns = _build_allocation(enriched, key_fn=lambda _atomic: "cash")
    assert len(breakdowns) == 1
    assert breakdowns[0].percentage == Decimal("0")
    assert breakdowns[0].count == 2


def test_build_allocation_splits_by_value_share() -> None:
    """AC17.4.4: non-zero total splits into the expected percentage shares."""
    categories = iter(["a", "b", "b"])
    enriched = [(object(), Decimal("25")), (object(), Decimal("50")), (object(), Decimal("25"))]
    breakdowns = {b.category: b for b in _build_allocation(enriched, key_fn=lambda _a: next(categories))}
    assert breakdowns["a"].percentage == Decimal("25")
    assert breakdowns["b"].percentage == Decimal("75")


def test_line_total_sums_and_quantizes() -> None:
    """AC5.2.1 / AC5.3.1: the shared income-statement/cash-flow total verb sums
    string/Decimal amounts and quantizes to 2dp (the body both reports now reuse)."""
    lines = [{"amount": "10.005"}, {"amount": Decimal("0.001")}, {"amount": "-2.50"}]
    assert _line_total(lines) == Decimal("7.51")
    assert _line_total([]) == Decimal("0.00")
