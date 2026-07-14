"""Behaviour-preserving guard for the #1253 ROI #6 value-type adoption.

Pins the *exact* prior behaviour of portfolio's allocation-share calculation
so the refactor (a ``> 0`` guard -> ``Ratio.fraction_or_zero``) cannot
silently drift.
"""

from __future__ import annotations

from decimal import Decimal

from src.portfolio.extension.allocation import _build_allocation


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
