"""Legacy valuation adapter tests (#1223, EPIC-011 AC11.23).

Proves the legacy -> stable bridge is total and deterministic, preserves the
legacy liquidity behaviour exactly (cross-checked against the live legacy table),
and projects a snapshot onto the stable read-model without losing traceability
fields. No persistence or report behaviour is exercised here.
"""

from datetime import date
from decimal import Decimal

from src.constants.valuation_taxonomy import (
    EconomicSide,
    LiquidityClass,
    ValuationL1,
    ValuationL2,
    default_side_for_l1,
)
from src.models.layer3 import (
    ManualValuationBasis,
    ManualValuationComponentType as Legacy,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.services.assets import _DEFAULT_LIQUIDITY_CLASS
from src.services.valuation_adapter import adapt_snapshot, classify_legacy_component


def test_legacy_component_mapping_is_total_and_deterministic():
    """AC11.23.1: every legacy component maps to stable codes; side = L1 default."""
    for legacy in Legacy:
        codes = classify_legacy_component(legacy)  # no KeyError => total
        assert isinstance(codes.l1, ValuationL1)
        assert isinstance(codes.l2, ValuationL2)
        assert codes.economic_side is default_side_for_l1(codes.l1)
    assert classify_legacy_component(Legacy.CPF_BALANCE) == classify_legacy_component(Legacy.CPF_BALANCE)


def test_adapter_preserves_legacy_liquidity_class():
    """AC11.23.2: adapter liquidity matches the legacy default for every component."""
    assert set(_DEFAULT_LIQUIDITY_CLASS) == set(Legacy)
    for legacy, legacy_liquidity in _DEFAULT_LIQUIDITY_CLASS.items():
        codes = classify_legacy_component(legacy)
        assert codes.liquidity_class.value == legacy_liquidity.value, legacy


def test_adapt_snapshot_preserves_fact_fields_in_stable_view():
    """AC11.23.3: snapshot projects onto the stable read-model preserving fields."""
    snap = ManualValuationSnapshot(
        component_type=Legacy.CPF_BALANCE,
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        as_of_date=date(2026, 3, 31),
        value=Decimal("150000.00"),
        currency="SGD",
        source="cpf_portal",
        valuation_basis=ManualValuationBasis.GOVERNMENT_STATEMENT,
    )
    view = adapt_snapshot(snap)
    assert view.as_of_date == date(2026, 3, 31)
    assert view.value == Decimal("150000.00")
    assert view.currency == "SGD"
    assert view.source == "cpf_portal"
    assert view.valuation_basis == "government_statement"
    assert view.component_type == "cpf_balance"
    assert view.confidence == Decimal("1.0")
    assert view.codes.l1 is ValuationL1.RETIREMENT_AND_BENEFIT
    assert view.codes.l2 is ValuationL2.MANDATORY_RETIREMENT


def test_legacy_fixtures_classify_to_expected_stable_codes():
    """AC11.23.4: CPF/insurance cash value/RSU/mortgage map to expected stable codes.

    Insurance cash value is an asset (never coverage), restricted compensation is
    an equity award, and liabilities carry the liability side.
    """
    cpf = classify_legacy_component(Legacy.CPF_BALANCE)
    assert (cpf.l1, cpf.l2, cpf.economic_side) == (
        ValuationL1.RETIREMENT_AND_BENEFIT,
        ValuationL2.MANDATORY_RETIREMENT,
        EconomicSide.ASSET,
    )

    cash_value = classify_legacy_component(Legacy.INSURANCE_CASH_VALUE)
    assert cash_value.economic_side is EconomicSide.ASSET
    assert cash_value.l1 is ValuationL1.RETIREMENT_AND_BENEFIT

    rsu = classify_legacy_component(Legacy.RSU)
    assert (rsu.l1, rsu.l2) == (ValuationL1.RESTRICTED_COMPENSATION, ValuationL2.EQUITY_AWARD)

    mortgage = classify_legacy_component(Legacy.MORTGAGE_BALANCE)
    assert mortgage.economic_side is EconomicSide.LIABILITY
    assert mortgage.liquidity_class is LiquidityClass.LIABILITY
