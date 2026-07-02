"""Python side of the cross-language ratio conformance suite (EPIC-012 AC12.9, #1167).

Drives the Python reference (``common.audit.ratio``) off the SAME vectors the TypeScript
frontend uses (``common/audit/ratio/conformance/vectors.json``). Divergence on the
HALF_UP percent policy turns this (or its TS mirror) red.
"""

from decimal import Decimal

import pytest

from common.audit.ratio import PERCENT_DP, PERCENT_ROUNDING, Ratio
from common.audit.ratio.conformance import load_vectors
from common.testing.ac_proof import ac_proof

VECTORS = load_vectors()


@ac_proof(
    proof_id="test_ratio_conformance_to_percent",
    ac_ids=["AC-audit.9.2"],
    ci_tier="pr_ci",
    issue="#1167",
)
@pytest.mark.parametrize(
    "case", VECTORS["to_percent"], ids=lambda c: f"{c['ratio']}/{c['dp']}"
)
def test_AC12_9_2_to_percent_matches_standard(case):
    """AC-audit.9.2: Python to_percent matches the shared HALF_UP standard."""
    assert Ratio(Decimal(case["ratio"])).to_percent(case["dp"]) == Decimal(
        case["expected"]
    ), case


@ac_proof(
    proof_id="test_ratio_conformance_percent_of",
    ac_ids=["AC-audit.9.2"],
    ci_tier="pr_ci",
    issue="#1167",
)
@pytest.mark.parametrize(
    "case", VECTORS["percent_of"], ids=lambda c: f"{c['part']}/{c['whole']}"
)
def test_AC12_9_2_percent_of_matches_standard(case):
    """AC-audit.9.2: Python fraction(part, whole).to_percent matches the standard."""
    got = Ratio.fraction(Decimal(case["part"]), Decimal(case["whole"])).to_percent(
        case["dp"]
    )
    assert got == Decimal(case["expected"]), case


@ac_proof(
    proof_id="test_ratio_conformance_from_percent",
    ac_ids=["AC-audit.9.2"],
    ci_tier="pr_ci",
    issue="#1167",
)
def test_AC12_9_2_from_percent_round_trip():
    """AC-audit.9.2: from_percent round-trips back to the same percent."""
    for case in VECTORS["from_percent"]:
        assert Ratio.from_percent(Decimal(case["percent"])).to_percent(2) == Decimal(
            case["expected_percent_2dp"]
        ), case
    assert PERCENT_DP == VECTORS["percent_dp"]
    assert PERCENT_ROUNDING == VECTORS["percent_rounding"]
