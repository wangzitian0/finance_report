"""Backend boundary-codec proofs for the audit value language."""

from decimal import Decimal

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.money import (
    ExchangeRate,
    FloatNotAllowedError as MoneyFloatNotAllowedError,
    InvalidMoneyPayloadError,
    Money,
    MoneyTolerance,
    exchange_rate_from_db_fields,
    exchange_rate_from_wire,
    exchange_rate_to_db_fields,
    exchange_rate_to_wire,
    money_from_db_fields,
    money_from_wire,
    money_to_db_fields,
    money_to_wire,
)
from src.audit.quantity import (
    InvalidQuantityPayloadError,
    Quantity,
    quantity_from_db_fields,
    quantity_from_wire,
    quantity_to_db_fields,
    quantity_to_wire,
)
from src.audit.ratio import Ratio, ratio_from_db_value, ratio_from_wire, ratio_to_db_value, ratio_to_wire
from src.audit.unit_price import (
    InvalidUnitPricePayloadError,
    UnitPrice,
    unit_price_from_db_fields,
    unit_price_from_wire,
    unit_price_to_db_fields,
    unit_price_to_wire,
)

pytestmark = pytest.mark.no_db


@ac_proof(
    proof_id="test_audit_boundary_codecs_preserve_typed_decimal_values",
    ac_ids=["AC-audit.31.4", "AC-audit.33.1"],
    ci_tier="pr_ci",
    issue="#950",
)
def test_AC_audit_31_4_boundary_codecs_preserve_typed_decimal_values():
    """AC-audit.31.4 / AC-audit.33.1: codecs preserve exact typed decimal values."""
    money = Money(Decimal("12.3400"), "USD")
    assert money_to_wire(money) == {"amount": "12.34", "currency": "USD"}
    assert money_from_wire({"amount": "12.34", "currency": "USD"}) == money
    assert money_to_db_fields(money) == {"amount": Decimal("12.3400"), "currency": "USD"}
    assert money_from_db_fields(Decimal("12.3400"), "USD") == money
    for encoder in (money_to_wire, money_to_db_fields):
        with pytest.raises(TypeError, match="expects Money"):
            encoder(object())  # type: ignore[arg-type]
    with pytest.raises(InvalidMoneyPayloadError, match="missing 'amount'"):
        money_from_wire({"currency": "USD"})
    with pytest.raises(MoneyFloatNotAllowedError, match="decimal string"):
        money_from_wire({"amount": 12.34, "currency": "USD"})

    rate = ExchangeRate("USD", "SGD", Decimal("1.3500"))
    assert exchange_rate_to_wire(rate) == {"base": "USD", "quote": "SGD", "rate": "1.35"}
    assert exchange_rate_from_wire({"base": "USD", "quote": "SGD", "rate": "1.35"}) == rate
    assert exchange_rate_to_db_fields(rate) == {"base": "USD", "quote": "SGD", "rate": Decimal("1.3500")}
    assert exchange_rate_from_db_fields("USD", "SGD", Decimal("1.3500")) == rate
    for encoder in (exchange_rate_to_wire, exchange_rate_to_db_fields):
        with pytest.raises(TypeError, match="expects ExchangeRate"):
            encoder(object())  # type: ignore[arg-type]

    ratio = Ratio(Decimal("0.125"))
    assert ratio_to_wire(ratio) == "0.125"
    assert ratio_from_wire("0.125") == ratio
    assert ratio_to_db_value(ratio) == Decimal("0.125")
    assert ratio_from_db_value(Decimal("0.125")) == ratio
    for encoder in (ratio_to_wire, ratio_to_db_value):
        with pytest.raises(TypeError, match="expects Ratio"):
            encoder(object())  # type: ignore[arg-type]

    quantity = Quantity(Decimal("3.500000"), "shares")
    assert quantity_to_wire(quantity) == {"value": "3.5", "unit": "shares"}
    assert quantity_from_wire({"value": "3.5", "unit": "shares"}) == quantity
    assert quantity_to_db_fields(quantity) == {"value": Decimal("3.500000"), "unit": "shares"}
    assert quantity_from_db_fields(Decimal("3.500000"), "shares") == quantity
    for encoder in (quantity_to_wire, quantity_to_db_fields):
        with pytest.raises(TypeError, match="expects Quantity"):
            encoder(object())  # type: ignore[arg-type]
    with pytest.raises(InvalidQuantityPayloadError, match="missing 'unit'"):
        quantity_from_wire({"value": "3.5"})

    unit_price = UnitPrice(Decimal("4.250000"), "USD", "shares")
    assert unit_price_to_wire(unit_price) == {"rate": "4.25", "currency": "USD", "unit": "shares"}
    assert unit_price_from_wire({"rate": "4.25", "currency": "USD", "unit": "shares"}) == unit_price
    assert unit_price_to_db_fields(unit_price) == {
        "rate": Decimal("4.250000"),
        "currency": "USD",
        "unit": "shares",
    }
    assert unit_price_from_db_fields(Decimal("4.250000"), "USD", "shares") == unit_price
    for encoder in (unit_price_to_wire, unit_price_to_db_fields):
        with pytest.raises(TypeError, match="expects UnitPrice"):
            encoder(object())  # type: ignore[arg-type]
    with pytest.raises(InvalidUnitPricePayloadError, match="missing 'rate'"):
        unit_price_from_wire({"currency": "USD", "unit": "shares"})


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
