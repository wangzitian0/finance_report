"""Canonical money rounding policy tests (docs/ssot/accounting.md#decimal-rule)."""

from decimal import Decimal

import pytest

from src.utils.money import MONEY_QUANTUM, to_money

pytestmark = pytest.mark.no_db


def test_money_quantum_is_two_decimal_places():
    assert MONEY_QUANTUM == Decimal("0.01")


def test_to_money_quantizes_to_two_decimal_places():
    assert to_money(Decimal("10")) == Decimal("10.00")
    assert to_money(Decimal("3.14159")) == Decimal("3.14")
    assert to_money(Decimal("0.1")) == Decimal("0.10")


@pytest.mark.parametrize(
    "value,expected",
    [
        # Exact-half cases distinguish banker's rounding from round-half-up.
        ("0.125", "0.12"),  # half to even (2 is even) — HALF_UP would give 0.13
        ("0.135", "0.14"),  # half to even (4 is even)
        ("0.145", "0.14"),  # half to even (4 is even) — HALF_UP would give 0.15
        ("0.155", "0.16"),  # half to even (6 is even)
        ("2.005", "2.00"),  # half to even (0 is even) — HALF_UP would give 2.01
    ],
)
def test_to_money_uses_banker_rounding_half_to_even(value, expected):
    assert to_money(Decimal(value)) == Decimal(expected)


def test_to_money_banker_rounding_is_symmetric_for_negatives():
    assert to_money(Decimal("-0.125")) == Decimal("-0.12")
    assert to_money(Decimal("-0.145")) == Decimal("-0.14")


def test_to_money_preserves_already_rounded_values():
    assert to_money(Decimal("99.99")) == Decimal("99.99")
    assert to_money(Decimal("-42.00")) == Decimal("-42.00")
