"""Backend unit-price module conformance (EPIC-012 AC12.32)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.money import Money
from src.audit.quantity import Quantity
from src.audit.unit_price import (
    UNIT_PRICE_DP,
    UNIT_PRICE_QUANTUM,
    UNIT_PRICE_ROUNDING,
    FloatNotAllowedError,
    UndefinedUnitPriceError,
    UnitMismatchError,
    UnitPrice,
)

pytestmark = pytest.mark.no_db

_VECTORS = json.loads(
    (Path(__file__).resolve().parents[5] / "common/audit/unit_price/conformance/vectors.json").read_text()
)


@ac_proof(proof_id="test_unit_price_backend_value_type", ac_ids=["AC12.32.1"], ci_tier="pr_ci")
def test_AC12_32_1_backend_unit_price_value_type_laws():
    """AC12.32.1: src.audit.unit_price rejects float, uses the 6-dp policy, guards units."""
    assert UNIT_PRICE_DP == 6
    assert UNIT_PRICE_QUANTUM == Decimal("0.000001")
    assert UNIT_PRICE_ROUNDING == "ROUND_HALF_UP"
    with pytest.raises(FloatNotAllowedError):
        UnitPrice(0.1, "USD", "shares")
    with pytest.raises(FloatNotAllowedError):
        UnitPrice(True, "USD", "shares")
    price = UnitPrice(Decimal("10.50"), "SGD", "shares")
    assert price * Quantity(Decimal("3"), "shares") == Money(Decimal("31.50"), "SGD")
    with pytest.raises(UnitMismatchError):
        price * Quantity(Decimal("1"), "contracts")
    with pytest.raises(UndefinedUnitPriceError):
        UnitPrice.from_total(Money(Decimal("1.00"), "USD"), Quantity(Decimal("0"), "shares"))


@ac_proof(proof_id="test_unit_price_backend_matches_vectors", ac_ids=["AC12.32.2"], ci_tier="pr_ci")
def test_AC12_32_2_backend_unit_price_matches_standard():
    """AC12.32.2: the shipped backend reproduces the shared conformance vectors."""
    for case in _VECTORS["quantize"]:
        got = UnitPrice(Decimal(case["rate"]), case["currency"], case["unit"]).quantize()
        assert got.rate == Decimal(case["expected"]), case
    for case in _VECTORS["product"]:
        money = UnitPrice(Decimal(case["rate"]), case["currency"], case["unit"]) * Quantity(
            Decimal(case["quantity"]), case["unit"]
        )
        assert money == Money(Decimal(case["expected_amount"]), case["currency"]), case
    for case in _VECTORS["from_total"]:
        derived = UnitPrice.from_total(
            Money(Decimal(case["amount"]), case["currency"]),
            Quantity(Decimal(case["quantity"]), case["unit"]),
        )
        assert derived.quantize().rate == Decimal(case["expected_rate_6dp"]), case
