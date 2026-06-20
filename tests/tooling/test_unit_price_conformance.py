"""Python side of the cross-language unit-price conformance suite (EPIC-012 AC12.32)."""

from decimal import Decimal

import pytest
from common.money import Money
from common.quantity import Quantity
from common.testing.ac_proof import ac_proof
from common.unit_price import (
    UNIT_PRICE_DP,
    UNIT_PRICE_QUANTUM,
    UNIT_PRICE_ROUNDING,
    UndefinedUnitPriceError,
    UnitMismatchError,
    UnitPrice,
)
from common.unit_price.conformance import load_vectors

VECTORS = load_vectors()


@ac_proof(
    proof_id="test_unit_price_conformance_constants",
    ac_ids=["AC12.32.2"],
    ci_tier="pr_ci",
)
def test_AC12_32_2_unit_price_policy_matches_standard():
    """AC12.32.2: the price quantum/policy matches the shared standard."""
    assert str(UNIT_PRICE_QUANTUM) == VECTORS["unit_price_quantum"]
    assert UNIT_PRICE_DP == VECTORS["unit_price_dp"]
    assert UNIT_PRICE_ROUNDING == VECTORS["default_rounding"]


@ac_proof(
    proof_id="test_unit_price_conformance_quantize",
    ac_ids=["AC12.32.2"],
    ci_tier="pr_ci",
)
@pytest.mark.parametrize(
    "case", VECTORS["quantize"], ids=lambda c: f"{c['rate']}/{c['unit']}"
)
def test_AC12_32_2_unit_price_quantize_matches_standard(case):
    """AC12.32.2: Python UnitPrice.quantize matches the shared 6-dp standard."""
    got = UnitPrice(Decimal(case["rate"]), case["currency"], case["unit"]).quantize()
    assert got.rate == Decimal(case["expected"]), case


@ac_proof(
    proof_id="test_unit_price_conformance_product",
    ac_ids=["AC12.32.2"],
    ci_tier="pr_ci",
)
@pytest.mark.parametrize(
    "case", VECTORS["product"], ids=lambda c: f"{c['rate']}x{c['quantity']}"
)
def test_AC12_32_2_unit_price_product_matches_standard(case):
    """AC12.32.2: price * quantity reproduces the shared (exact) money amount."""
    price = UnitPrice(Decimal(case["rate"]), case["currency"], case["unit"])
    money = price * Quantity(Decimal(case["quantity"]), case["unit"])
    assert money == Money(Decimal(case["expected_amount"]), case["currency"]), case


@ac_proof(
    proof_id="test_unit_price_conformance_from_total",
    ac_ids=["AC12.32.2"],
    ci_tier="pr_ci",
)
@pytest.mark.parametrize(
    "case", VECTORS["from_total"], ids=lambda c: f"{c['amount']}/{c['quantity']}"
)
def test_AC12_32_2_unit_price_from_total_matches_standard(case):
    """AC12.32.2: from_total(...).quantize() reproduces the shared 6-dp rate."""
    derived = UnitPrice.from_total(
        Money(Decimal(case["amount"]), case["currency"]),
        Quantity(Decimal(case["quantity"]), case["unit"]),
    )
    assert derived.quantize().rate == Decimal(case["expected_rate_6dp"]), case


@ac_proof(
    proof_id="test_unit_price_conformance_errors", ac_ids=["AC12.32.2"], ci_tier="pr_ci"
)
def test_AC12_32_2_unit_price_error_cases_match_standard():
    """AC12.32.2: zero-quantity and unit-mismatch raise per the shared standard."""
    for case in VECTORS["from_total_undefined"]:
        with pytest.raises(UndefinedUnitPriceError):
            UnitPrice.from_total(
                Money(Decimal(case["amount"]), case["currency"]),
                Quantity(Decimal(case["quantity"]), case["unit"]),
            )
    for case in VECTORS["unit_mismatch"]:
        with pytest.raises(UnitMismatchError):
            UnitPrice(Decimal(case["rate"]), case["currency"], case["unit"]) * Quantity(
                Decimal(case["quantity"]), case["quantity_unit"]
            )
