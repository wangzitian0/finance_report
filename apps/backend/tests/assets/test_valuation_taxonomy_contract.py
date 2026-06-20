"""Stable valuation taxonomy contract tests (#1221, EPIC-011 AC11.21).

These pin the durable contract that storage (#1222), the legacy adapter
(#1223), LLM classification (#1224), and report consumption (#1225) depend on.
The guard test is the load-bearing one: it rejects any attempt to smuggle a
jurisdiction-, scheme-, or vendor-specific name back into the stable codes.
"""

from src.constants.valuation_taxonomy import (
    FORBIDDEN_CODE_TOKENS,
    L1_DEFAULT_SIDE,
    L2_PARENT,
    EconomicSide,
    LiquidityClass,
    ValuationL1,
    ValuationL2,
    ValuationRole,
    all_stable_codes,
    default_side_for_l1,
    parent_l1,
)


def test_l1_taxonomy_covers_required_stable_classes():
    """AC11.21.1: L1 defines the required durable classes incl. fallbacks."""
    required = {
        "cash",
        "marketable_investment",
        "retirement_and_benefit",
        "restricted_compensation",
        "real_estate",
        "liability",
        "other_asset",  # fallback asset
        "non_asset",  # fallback non-net-worth (e.g. coverage)
    }
    assert {c.value for c in ValuationL1} == required


def test_report_stable_dimensions_present():
    """AC11.21.2: economic_side, valuation_role, liquidity_class are defined.

    Insurance cash value vs coverage is expressible by side + role: cash value
    is an asset-side net-worth component, whereas a coverage amount sits on the
    non_asset side with the coverage_amount role, so it is excluded from net
    worth.
    """
    assert {s.value for s in EconomicSide} == {"asset", "liability", "non_asset"}
    assert ValuationRole.COVERAGE_AMOUNT.value == "coverage_amount"
    assert ValuationRole.NET_WORTH_COMPONENT.value == "net_worth_component"
    assert {c.value for c in LiquidityClass} == {
        "liquid",
        "restricted",
        "illiquid",
        "liability",
    }


def test_stable_codes_reject_vendor_jurisdiction_scheme_tokens():
    """AC11.21.3: no stable code carries a forbidden product/jurisdiction token.

    Guards against CPF/401k/MPF/SRS/IRA/RSU/ESOP/insurer/country names creeping
    back into the durable taxonomy. Those belong in extracted metadata only.
    """
    violations = []
    for code in all_stable_codes():
        lowered = code.lower()
        for token in FORBIDDEN_CODE_TOKENS:
            if token in lowered:
                violations.append((code, token))
    assert not violations, (
        f"Stable taxonomy codes must not contain jurisdiction/scheme/vendor tokens; offenders: {violations}"
    )


def test_l2_maps_to_single_l1_and_default_side():
    """AC11.21.4: every L2 has exactly one L1 parent with a default side."""
    # Every L2 member is mapped, and nothing extra is mapped.
    assert set(L2_PARENT) == set(ValuationL2)
    # Every L1 has a default economic side, and nothing extra.
    assert set(L1_DEFAULT_SIDE) == set(ValuationL1)
    # The lookup helpers agree with the tables for every member.
    for l2 in ValuationL2:
        parent = parent_l1(l2)
        assert isinstance(parent, ValuationL1)
        assert default_side_for_l1(parent) is L1_DEFAULT_SIDE[parent]
    # Liabilities roll up to the liability side; coverage to non_asset.
    assert default_side_for_l1(parent_l1(ValuationL2.SECURED_LIABILITY)) is (EconomicSide.LIABILITY)
    assert default_side_for_l1(parent_l1(ValuationL2.PROTECTION_COVERAGE)) is (EconomicSide.NON_ASSET)
