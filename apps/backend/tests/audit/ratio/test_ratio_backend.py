"""Backend ratio module (src.audit.ratio) — value-type + conformance (EPIC-012 AC12.9, #1167).

Proves the backend's shipped ``src.audit.ratio`` end conforms to the shared standard and
fully exercises the module (the backend image ships src.audit.ratio; common/ is not
shipped). Mirrors common.audit.ratio, kept in lockstep by the conformance vectors.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.ratio import (
    PERCENT_DP,
    PERCENT_ROUNDING,
    FloatNotAllowedError,
    Ratio,
    UndefinedRatioError,
)

pytestmark = pytest.mark.no_db

_VECTORS = json.loads((Path(__file__).resolve().parents[5] / "common/audit/ratio/conformance/vectors.json").read_text())


@ac_proof(proof_id="test_ratio_backend_conformance", ac_ids=["AC-audit.9.2"], ci_tier="pr_ci", issue="#1167")
@pytest.mark.parametrize("case", _VECTORS["to_percent"], ids=lambda c: c["ratio"])
def test_AC12_9_2_backend_to_percent_matches(case):
    """AC-audit.9.2: src.audit.ratio to_percent matches the shared standard."""
    assert Ratio(Decimal(case["ratio"])).to_percent(case["dp"]) == Decimal(case["expected"])


@ac_proof(proof_id="test_ratio_backend_percent_of", ac_ids=["AC-audit.9.2"], ci_tier="pr_ci", issue="#1167")
@pytest.mark.parametrize("case", _VECTORS["percent_of"], ids=lambda c: f"{c['part']}/{c['whole']}")
def test_AC12_9_2_backend_percent_of_matches(case):
    """AC-audit.9.2: src.audit.ratio fraction(part, whole).to_percent matches the standard."""
    assert Ratio.fraction(Decimal(case["part"]), Decimal(case["whole"])).to_percent(case["dp"]) == Decimal(
        case["expected"]
    )


@ac_proof(proof_id="test_ratio_backend_value_type", ac_ids=["AC-audit.9.1"], ci_tier="pr_ci", issue="#1167")
def test_AC12_9_1_backend_value_type_laws():
    """AC-audit.9.1: src.audit.ratio rejects float, zero-whole undefined, percent policy, arithmetic."""
    assert PERCENT_DP == 2 and PERCENT_ROUNDING == "ROUND_HALF_UP"
    with pytest.raises(FloatNotAllowedError):
        Ratio(0.1)
    with pytest.raises(FloatNotAllowedError):
        Ratio(True)
    with pytest.raises(FloatNotAllowedError):
        Ratio("0.1")  # str rejected in Python (use Decimal)
    with pytest.raises(UndefinedRatioError):
        Ratio.fraction(1, 0)
    a, b = Ratio(Decimal("0.1")), Ratio(Decimal("0.2"))
    assert (a + b) == Ratio(Decimal("0.3"))
    assert (b - a) == Ratio(Decimal("0.1"))
    assert (-a) == Ratio(Decimal("-0.1"))
    assert (2 * a) == Ratio(Decimal("0.2"))
    assert a < b and a <= b and b > a and b >= a
    assert Ratio.from_percent(Decimal("50")).to_percent() == Decimal("50.00")
    assert str(a) == "10.00%"
    assert Ratio.zero().value == Decimal("0")
    assert Ratio.zero().is_zero()
    assert not a.is_zero()
    # A non-Ratio operand is a TypeError (mirrors Money's cross-type guard).
    with pytest.raises(TypeError):
        _ = a - 0.1  # type: ignore[operator]
