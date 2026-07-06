"""Tolerance policy contract tests."""

from decimal import Decimal

from src.extraction import validation
from src.extraction.extension import statement_validation


def test_ac16_22_7_tolerance_policy_constants_are_intentional():
    """AC16.22.7: Stage 1 approval and extraction scoring use documented separate tolerances."""
    assert statement_validation.BALANCE_TOLERANCE == Decimal("0.001")
    assert validation.BALANCE_TOLERANCE == Decimal("0.10")
