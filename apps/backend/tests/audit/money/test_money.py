from decimal import Decimal

import pytest

from src.audit.money import MONEY_QUANTUM, to_money

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10", "10.00"), ("3.14159", "3.14"), ("0.1", "0.10"), ("-0.125", "-0.12"), ("-0.145", "-0.14"),
        ("99.99", "99.99"), ("-42.00", "-42.00"), ("0.125", "0.12"), ("0.135", "0.14"), ("0.145", "0.14"),
        ("0.155", "0.16"), ("2.005", "2.00"),
    ],
)
def test_to_money_quantum_and_banker_rounding(value: str, expected: str) -> None:
    assert MONEY_QUANTUM == Decimal("0.01") and to_money(Decimal(value)) == Decimal(expected)
