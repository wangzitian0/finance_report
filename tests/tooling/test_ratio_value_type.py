"""Ratio value-type behavioural proofs (EPIC-012 AC12.9, #1167 base-package family).

Exercises the ``common.ratio`` narrow waist: construction (rejects float),
``fraction`` (zero-whole undefined), the single percent-display policy
(2 dp / HALF_UP), and dimensionless arithmetic.

Contract: ``common/ratio/contract/ratio.contract.md``.
"""

from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from common.ratio import (
    PERCENT_DP,
    PERCENT_ROUNDING,
    FloatNotAllowedError,
    Ratio,
    RatioError,
    UndefinedRatioError,
)
from common.testing.ac_proof import ac_proof


@ac_proof(proof_id="test_ratio_rejects_float", ac_ids=["AC12.9.1"], ci_tier="pr_ci", issue="#1167")
def test_AC12_9_1_ratio_rejects_float_and_is_decimal_backed():
    """AC12.9.1: Ratio rejects float/bool, is Decimal-backed and immutable."""
    with pytest.raises(FloatNotAllowedError):
        Ratio(0.125)
    with pytest.raises(FloatNotAllowedError):
        Ratio(True)
    with pytest.raises(FloatNotAllowedError):
        Ratio("0.1")  # str not accepted in Python (use Decimal); FE accepts string
    assert isinstance(Ratio(1).value, Decimal)
    r = Ratio(Decimal("0.125"))
    with pytest.raises((AttributeError, TypeError)):
        r.value = Decimal("0.2")  # type: ignore[misc]


@ac_proof(proof_id="test_ratio_percent_policy", ac_ids=["AC12.9.1"], ci_tier="pr_ci", issue="#1167")
def test_AC12_9_1_percent_display_is_half_up_two_dp():
    """AC12.9.1: percent display is the canonical 2 dp / ROUND_HALF_UP (not HALF_EVEN)."""
    assert PERCENT_DP == 2
    assert PERCENT_ROUNDING != ROUND_HALF_EVEN  # explicitly NOT money's rounding
    # 12.005% -> HALF_UP -> 12.01 (HALF_EVEN would give 12.00)
    assert Ratio(Decimal("0.12005")).to_percent() == Decimal("12.01")
    assert Ratio(Decimal("0.125")).to_percent() == Decimal("12.50")
    assert Ratio(Decimal("0.125")).format_percent() == "12.50%"
    assert Ratio(Decimal("0.123455")).to_percent(4) == Decimal("12.3455")


@ac_proof(proof_id="test_ratio_fraction", ac_ids=["AC12.9.1"], ci_tier="pr_ci", issue="#1167")
def test_AC12_9_1_fraction_and_zero_whole_is_undefined():
    """AC12.9.1: fraction(part, whole) builds the ratio; a zero whole raises."""
    assert Ratio.fraction(1, 8).to_percent() == Decimal("12.50")
    assert Ratio.fraction(Decimal("2"), Decimal("3")).to_percent() == Decimal("66.67")
    assert Ratio.from_percent(Decimal("12.5")).to_percent() == Decimal("12.50")
    with pytest.raises(UndefinedRatioError):
        Ratio.fraction(1, 0)
    assert isinstance(UndefinedRatioError("x"), RatioError)


@ac_proof(proof_id="test_ratio_arithmetic", ac_ids=["AC12.9.1"], ci_tier="pr_ci", issue="#1167")
def test_AC12_9_1_dimensionless_arithmetic_and_compare():
    """AC12.9.1: ratios add/sub/scale/compare (dimensionless)."""
    a, b = Ratio(Decimal("0.1")), Ratio(Decimal("0.2"))
    assert (a + b) == Ratio(Decimal("0.3"))
    assert (b - a) == Ratio(Decimal("0.1"))
    assert (-a) == Ratio(Decimal("-0.1"))
    assert (a * 3) == Ratio(Decimal("0.3"))
    assert (3 * a) == Ratio(Decimal("0.3"))
    assert a < b and a <= b and b > a and b >= a
    assert str(Ratio(Decimal("0.5"))) == "50.00%"
    assert Ratio.zero() == Ratio(Decimal("0"))
    # A non-Ratio operand is a TypeError (mirrors Money's cross-type guard).
    with pytest.raises(TypeError):
        _ = a + 0.1  # type: ignore[operator]
