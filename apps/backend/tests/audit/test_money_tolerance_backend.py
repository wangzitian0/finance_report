"""Backend proofs for the audit money tolerance band."""

from decimal import Decimal

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.money import Money, MoneyTolerance
from src.audit.ratio import Ratio

pytestmark = pytest.mark.no_db


@ac_proof(
    proof_id="test_money_tolerance_rejects_invalid_bands_and_scales_exactly",
    ac_ids=["AC-audit.33.1"],
    ci_tier="pr_ci",
    issue="#950",
)
def test_AC_audit_33_1_money_tolerance_validates_and_scales_exactly():
    """AC-audit.33.1: tolerance is typed, currency-aware, and scales exactly."""
    tolerance = MoneyTolerance(Money(Decimal("1.00"), "USD"), Ratio.from_percent(Decimal("5")))
    assert tolerance.threshold_for(Money(Decimal("10.00"), "USD")) == Money(Decimal("1.00"), "USD")
    assert tolerance.threshold_for(Money(Decimal("100.00"), "USD")) == Money(Decimal("5.00"), "USD")
    assert tolerance.holds(Money(Decimal("104.99"), "USD"), Money(Decimal("100.00"), "USD"))
    assert not tolerance.holds(Money(Decimal("105.01"), "USD"), Money(Decimal("100.00"), "USD"))
    assert tolerance.scaled(Decimal("2")) == MoneyTolerance(
        Money(Decimal("2.00"), "USD"), Ratio.from_percent(Decimal("10"))
    )
    assert tolerance.scaled(2) == tolerance.scaled(Decimal("2"))
    with pytest.raises(TypeError, match="absolute must be Money"):
        MoneyTolerance(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="relative must be Ratio"):
        MoneyTolerance(Money(Decimal("1.00"), "USD"), object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="absolute tolerance"):
        MoneyTolerance(Money(Decimal("-0.01"), "USD"))
    with pytest.raises(ValueError, match="relative tolerance"):
        MoneyTolerance(Money(Decimal("0"), "USD"), Ratio(Decimal("-0.01")))
    with pytest.raises(TypeError, match="scale factor"):
        tolerance.scaled(True)
    with pytest.raises(ValueError, match="scale factor"):
        tolerance.scaled(Decimal("-1"))
