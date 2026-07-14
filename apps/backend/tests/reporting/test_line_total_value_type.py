"""Behaviour-preserving guard for the #1253 ROI #2 value-type adoption.

Pins the *exact* prior behaviour of the shared income-statement/cash-flow
total verb so the refactor (reporting aggregations now call the shared
``_core._line_total`` verb) cannot silently drift.
"""

from __future__ import annotations

from decimal import Decimal

from src.reporting.extension._core import _line_total


def test_line_total_sums_and_quantizes() -> None:
    """AC5.2.1 / AC5.3.1: the shared income-statement/cash-flow total verb sums
    string/Decimal amounts and quantizes to 2dp (the body both reports now reuse)."""
    lines = [{"amount": "10.005"}, {"amount": Decimal("0.001")}, {"amount": "-2.50"}]
    assert _line_total(lines) == Decimal("7.51")
    assert _line_total([]) == Decimal("0.00")
