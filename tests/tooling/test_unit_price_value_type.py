"""UnitPrice value-type laws (EPIC-012 AC12.32).

The fourth base-element value type: a money-per-quantity composite that owns the
``quantity * price`` / ``total / quantity`` semantics and the 6-dp price quantum,
so portfolio/market-data services stop re-deriving them as raw ``Decimal`` glue.
"""

from decimal import Decimal

import pytest

from common.audit.money import Money
from common.audit.quantity import Quantity
from common.audit.unit_price import (
    UNIT_PRICE_DP,
    UNIT_PRICE_QUANTUM,
    UNIT_PRICE_ROUNDING,
    CurrencyMismatchError,
    FloatNotAllowedError,
    UndefinedUnitPriceError,
    UnitMismatchError,
    UnitPrice,
)
from common.testing.ac_proof import ac_proof


@ac_proof(
    proof_id="test_unit_price_rejects_float", ac_ids=["AC12.32.1"], ci_tier="pr_ci"
)
def test_AC12_32_1_unit_price_rejects_float_and_is_decimal_backed():
    """AC12.32.1: UnitPrice rejects float/bool, is Decimal-backed and immutable."""
    with pytest.raises(FloatNotAllowedError):
        UnitPrice(0.125, "SGD", "shares")
    with pytest.raises(FloatNotAllowedError):
        UnitPrice(True, "SGD", "shares")
    assert isinstance(UnitPrice(1, "SGD", "shares").rate, Decimal)
    price = UnitPrice(Decimal("1.25"), "SGD", "shares")
    with pytest.raises((AttributeError, TypeError)):
        price.rate = Decimal("2")  # type: ignore[misc]


@ac_proof(proof_id="test_unit_price_policy", ac_ids=["AC12.32.1"], ci_tier="pr_ci")
def test_AC12_32_1_unit_price_quantum_is_six_dp_half_up():
    """AC12.32.1: the price quantum is 6 dp / ROUND_HALF_UP, not the money quantum."""
    assert UNIT_PRICE_DP == 6
    assert UNIT_PRICE_QUANTUM == Decimal("0.000001")
    assert UNIT_PRICE_ROUNDING == "ROUND_HALF_UP"
    assert UnitPrice(Decimal("1.2345675"), "USD", "shares").quantize().rate == Decimal(
        "1.234568"
    )


@ac_proof(proof_id="test_unit_price_product", ac_ids=["AC12.32.1"], ci_tier="pr_ci")
def test_AC12_32_1_unit_price_times_quantity_is_money():
    """AC12.32.1: price * quantity yields exact Money in the price's currency."""
    price = UnitPrice(Decimal("10.50"), "SGD", "shares")
    qty = Quantity(Decimal("3"), "shares")
    assert price * qty == Money(Decimal("31.50"), "SGD")
    assert qty * price == Money(Decimal("31.50"), "SGD")  # __rmul__
    # exact / unquantized: sub-cent precision is preserved until the money boundary
    assert (
        UnitPrice(Decimal("1.005"), "USD", "shares") * Quantity(Decimal("1"), "shares")
    ).amount == Decimal("1.005")
    with pytest.raises(UnitMismatchError):
        price * Quantity(Decimal("3"), "contracts")


@ac_proof(proof_id="test_unit_price_from_total", ac_ids=["AC12.32.1"], ci_tier="pr_ci")
def test_AC12_32_1_unit_price_from_total_is_money_over_quantity():
    """AC12.32.1: from_total derives Money / Quantity; zero quantity is undefined."""
    derived = UnitPrice.from_total(
        Money(Decimal("100.00"), "SGD"), Quantity(Decimal("4"), "shares")
    )
    assert derived.quantize().rate == Decimal("25.000000")
    assert derived.currency.code == "SGD"
    assert derived.unit.code == "shares"
    with pytest.raises(UndefinedUnitPriceError):
        UnitPrice.from_total(
            Money(Decimal("10.00"), "USD"), Quantity(Decimal("0"), "shares")
        )


@ac_proof(proof_id="test_unit_price_compare", ac_ids=["AC12.32.1"], ci_tier="pr_ci")
def test_AC12_32_1_unit_price_compare_requires_same_currency_and_unit():
    """AC12.32.1: comparison is same-currency AND same-unit only."""
    a = UnitPrice(Decimal("5"), "USD", "shares")
    b = UnitPrice(Decimal("7"), "USD", "shares")
    assert a < b and b > a
    with pytest.raises(CurrencyMismatchError):
        a < UnitPrice(Decimal("7"), "SGD", "shares")
    with pytest.raises(UnitMismatchError):
        a < UnitPrice(Decimal("7"), "USD", "contracts")
