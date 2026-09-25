"""AC-reporting.cash-flow.1: Pure domain unit tests for cash flow bridge calculation and reconciliation."""

from decimal import Decimal

import pytest

from src.reporting.base.cash_flow_calculator import calculate_cash_flow_bridge

pytestmark = pytest.mark.no_db


def test_standard_cash_flow_reconciles():
    """AC-reporting.cash-flow.1: Standard cash movements reconcile without discrepancy."""
    # Beginning cash: 10,000.00
    # Operating: +3,000.00 (inflow)
    # Investing: -1,000.00 (equipment purchase)
    # Financing: -500.00 (loan principal payment)
    # Net movement: +1,500.00 -> Ending cash: 11,500.00
    bridge = calculate_cash_flow_bridge(
        beginning_cash=Decimal("10000.00"),
        ending_cash=Decimal("11500.00"),
        operating_total=Decimal("3000.00"),
        investing_total=Decimal("-1000.00"),
        financing_total=Decimal("-500.00"),
    )

    assert bridge.classified_activity == Decimal("1500.00")
    assert bridge.cash_delta == Decimal("1500.00")
    assert bridge.net_cash_flow == Decimal("1500.00")
    assert bridge.fx_effect == Decimal("0.00")
    assert bridge.discrepancy == Decimal("0.00")
    assert bridge.reconciles is True


def test_multicurrency_fx_effect_absorption():
    """AC-reporting.cash-flow.1: Multi-currency exchange rate drift is captured in fx_effect."""
    # When foreign currency cash increases in value due to exchange rate change,
    # cash_delta reflects the spot revaluation while classified activity was converted at event rates.
    bridge = calculate_cash_flow_bridge(
        beginning_cash=Decimal("5000.00"),
        ending_cash=Decimal("7200.00"),  # Delta = 2,200.00
        operating_total=Decimal("2000.00"),
        investing_total=Decimal("0.00"),
        financing_total=Decimal("0.00"),
        fx_effect=Decimal("200.00"),
    )

    assert bridge.cash_delta == Decimal("2200.00")
    assert bridge.classified_activity == Decimal("2000.00")
    assert bridge.fx_effect == Decimal("200.00")
    assert bridge.bridge_total == Decimal("2200.00")
    assert bridge.discrepancy == Decimal("0.00")
    assert bridge.reconciles is True


def test_opening_stock_adjustment_deduction():
    """AC-reporting.cash-flow.1: Opening stock adjustment isolates pre-existing cash positions."""
    # Beginning cash 0, Ending cash 10,000, but 10,000 was opening stock (not period net flow)
    bridge = calculate_cash_flow_bridge(
        beginning_cash=Decimal("0.00"),
        ending_cash=Decimal("10000.00"),
        operating_total=Decimal("0.00"),
        investing_total=Decimal("0.00"),
        financing_total=Decimal("0.00"),
        opening_stock_adjustment=Decimal("10000.00"),
    )

    assert bridge.cash_delta == Decimal("10000.00")
    assert bridge.net_cash_flow == Decimal("0.00")
    assert bridge.reconciles is True


def test_unclassified_cash_and_falsification_discrepancy():
    """Falsification test: Unexplained imbalance between cash delta and activities yields non-zero discrepancy."""
    # Ending cash is 15,000, Delta = 5,000, but only 4,000 is accounted for and no FX
    bridge = calculate_cash_flow_bridge(
        beginning_cash=Decimal("10000.00"),
        ending_cash=Decimal("15000.00"),
        operating_total=Decimal("4000.00"),
        investing_total=Decimal("0.00"),
        financing_total=Decimal("0.00"),
    )

    assert bridge.cash_delta == Decimal("5000.00")
    assert bridge.bridge_total == Decimal("4000.00")
    assert bridge.discrepancy == Decimal("1000.00")
    assert bridge.reconciles is False
