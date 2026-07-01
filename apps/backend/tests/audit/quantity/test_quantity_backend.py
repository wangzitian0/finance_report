"""Backend quantity module conformance (EPIC-012 AC12.30)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.quantity import (
    QUANTITY_DP,
    QUANTITY_QUANTUM,
    QUANTITY_ROUNDING,
    FloatNotAllowedError,
    Quantity,
    UnitMismatchError,
)
from src.audit.ratio import Ratio

pytestmark = pytest.mark.no_db

_VECTORS = json.loads(
    (Path(__file__).resolve().parents[5] / "common/audit/quantity/conformance/vectors.json").read_text()
)


@ac_proof(proof_id="test_quantity_backend_conformance", ac_ids=["AC-audit.30.2"], ci_tier="pr_ci")
@pytest.mark.parametrize("case", _VECTORS["quantize"], ids=lambda c: c["value"])
def test_AC12_30_2_backend_quantity_quantize_matches(case):
    """AC-audit.30.2: src.audit.quantity quantize matches the shared standard."""
    assert Quantity(Decimal(case["value"]), case["unit"]).quantize().value == Decimal(case["expected"])


@ac_proof(proof_id="test_quantity_backend_value_type", ac_ids=["AC-audit.30.1"], ci_tier="pr_ci")
def test_AC12_30_1_backend_quantity_value_type_laws():
    """AC-audit.30.1: src.audit.quantity rejects float, uses 6-dp policy, and guards units."""
    assert QUANTITY_DP == 6
    assert QUANTITY_QUANTUM == Decimal("0.000001")
    assert QUANTITY_ROUNDING == "ROUND_HALF_UP"
    with pytest.raises(FloatNotAllowedError):
        Quantity(0.1, "shares")
    with pytest.raises(FloatNotAllowedError):
        Quantity(True, "shares")
    a, b = Quantity(Decimal("1"), "shares"), Quantity(Decimal("3"), "shares")
    assert (a + b) == Quantity(Decimal("4"), "shares")
    assert (b - a) == Quantity(Decimal("2"), "shares")
    assert (2 * a) == Quantity(Decimal("2"), "shares")
    assert a < b
    assert a.ratio_to(b) == Ratio(Decimal("0.3333333333333333333333333333"))
    assert Quantity.zero("shares").is_zero()
    with pytest.raises(UnitMismatchError):
        _ = a + Quantity(Decimal("1"), "contracts")
