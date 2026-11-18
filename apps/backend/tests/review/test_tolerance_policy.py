from decimal import Decimal

from src.extraction import validation
from src.extraction.extension import statement_validation


def test_tolerance_policy_constants_are_intentional():
    assert (statement_validation.BALANCE_TOLERANCE, validation.BALANCE_TOLERANCE) == (Decimal("0.001"), Decimal("0.10"))
