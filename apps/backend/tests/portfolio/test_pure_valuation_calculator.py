"""AC-portfolio.valuation.1: Pure domain calculation tests for portfolio valuation and allocation.

Verifies mathematical reductions for position valuation, unrealized PnL,
portfolio aggregate totals, and allocation breakdown without DB/mock dependencies.
"""

from decimal import Decimal

import pytest

from src.portfolio.base.valuation_calculator import (
    AllocationItem,
    PortfolioValuationTotals,
    PositionValuationResult,
    calculate_allocation_breakdown,
    calculate_portfolio_valuation_totals,
    calculate_position_valuation,
)

pytestmark = pytest.mark.no_db


def test_calculate_position_valuation_profit():
    """Valuation on profitable position: market_value > cost_basis."""
    result = calculate_position_valuation(
        quantity=Decimal("100"),
        unit_cost_basis=Decimal("150.00"),
        market_price=Decimal("175.50"),
    )
    assert isinstance(result, PositionValuationResult)
    assert result.market_value == Decimal("17550.00")
    assert result.cost_basis == Decimal("15000.00")
    assert result.unrealized_pnl == Decimal("2550.00")
    # PnL% = 2550 / 15000 * 100 = 17.0%
    assert result.unrealized_pnl_percent == Decimal("17.00")


def test_calculate_position_valuation_loss():
    """Valuation on loss position: market_value < cost_basis."""
    result = calculate_position_valuation(
        quantity=Decimal("50"),
        unit_cost_basis=Decimal("200.00"),
        market_price=Decimal("180.00"),
    )
    assert result.market_value == Decimal("9000.00")
    assert result.cost_basis == Decimal("10000.00")
    assert result.unrealized_pnl == Decimal("-1000.00")
    # PnL% = -1000 / 10000 * 100 = -10.0%
    assert result.unrealized_pnl_percent == Decimal("-10.00")


def test_calculate_position_valuation_zero_quantity_or_cost():
    """Zero quantity or zero cost basis returns zero PnL and safe 0% ratio."""
    zero_qty = calculate_position_valuation(
        quantity=Decimal("0"),
        unit_cost_basis=Decimal("100.00"),
        market_price=Decimal("120.00"),
    )
    assert zero_qty.market_value == Decimal("0.00")
    assert zero_qty.cost_basis == Decimal("0.00")
    assert zero_qty.unrealized_pnl == Decimal("0.00")
    assert zero_qty.unrealized_pnl_percent == Decimal("0.00")

    zero_cost = calculate_position_valuation(
        quantity=Decimal("10"),
        unit_cost_basis=Decimal("0.00"),
        market_price=Decimal("50.00"),
    )
    assert zero_cost.cost_basis == Decimal("0.00")
    assert zero_cost.unrealized_pnl == Decimal("500.00")
    assert zero_cost.unrealized_pnl_percent == Decimal("0.00")


def test_calculate_position_valuation_negative_inputs_rejected():
    """Falsification: Negative quantity, price, or cost basis must raise ValueError."""
    with pytest.raises(ValueError, match="Quantity cannot be negative"):
        calculate_position_valuation(
            quantity=Decimal("-10"),
            unit_cost_basis=Decimal("100.00"),
            market_price=Decimal("120.00"),
        )

    with pytest.raises(ValueError, match="Market price cannot be negative"):
        calculate_position_valuation(
            quantity=Decimal("10"),
            unit_cost_basis=Decimal("100.00"),
            market_price=Decimal("-5.00"),
        )

    with pytest.raises(ValueError, match="Cost basis cannot be negative"):
        calculate_position_valuation(
            quantity=Decimal("10"),
            unit_cost_basis=Decimal("-100.00"),
            market_price=Decimal("120.00"),
        )


def test_calculate_portfolio_valuation_totals():
    """Aggregating multiple positions derives total market value, cost basis, and net PnL%."""
    pos1 = calculate_position_valuation(
        quantity=Decimal("100"),
        unit_cost_basis=Decimal("50.00"),
        market_price=Decimal("70.00"),
    )  # mv=7000, cost=5000, pnl=+2000
    pos2 = calculate_position_valuation(
        quantity=Decimal("200"),
        unit_cost_basis=Decimal("100.00"),
        market_price=Decimal("90.00"),
    )  # mv=18000, cost=20000, pnl=-2000
    pos3 = calculate_position_valuation(
        quantity=Decimal("50"),
        unit_cost_basis=Decimal("10.00"),
        market_price=Decimal("15.00"),
    )  # mv=750, cost=500, pnl=+250

    totals = calculate_portfolio_valuation_totals([pos1, pos2, pos3])
    assert isinstance(totals, PortfolioValuationTotals)
    assert totals.total_market_value == Decimal("25750.00")
    assert totals.total_cost_basis == Decimal("25500.00")
    assert totals.total_unrealized_pnl == Decimal("250.00")
    # 250 / 25500 * 100 = ~0.98%
    assert totals.total_unrealized_pnl_percent == Decimal("0.98")


def test_calculate_portfolio_valuation_totals_empty():
    """Empty position list produces zero totals."""
    totals = calculate_portfolio_valuation_totals([])
    assert totals.total_market_value == Decimal("0.00")
    assert totals.total_cost_basis == Decimal("0.00")
    assert totals.total_unrealized_pnl == Decimal("0.00")
    assert totals.total_unrealized_pnl_percent == Decimal("0.00")


def test_calculate_allocation_breakdown():
    """Allocation breakdown aggregates categories, computes percentages, and sorts descending."""
    items = [
        AllocationItem(category="Technology", value=Decimal("6000.00")),
        AllocationItem(category="Finance", value=Decimal("3000.00")),
        AllocationItem(category="Technology", value=Decimal("4000.00")),
        AllocationItem(category="Healthcare", value=Decimal("7000.00")),
    ]
    # Total = 6000 + 3000 + 4000 + 7000 = 20000
    # Technology: 10000 (50.00%, count 2)
    # Healthcare: 7000 (35.00%, count 1)
    # Finance: 3000 (15.00%, count 1)

    breakdown = calculate_allocation_breakdown(items)
    assert len(breakdown) == 3
    assert breakdown[0].category == "Technology"
    assert breakdown[0].value == Decimal("10000.00")
    assert breakdown[0].percentage == Decimal("50.00")
    assert breakdown[0].count == 2

    assert breakdown[1].category == "Healthcare"
    assert breakdown[1].value == Decimal("7000.00")
    assert breakdown[1].percentage == Decimal("35.00")
    assert breakdown[1].count == 1

    assert breakdown[2].category == "Finance"
    assert breakdown[2].value == Decimal("3000.00")
    assert breakdown[2].percentage == Decimal("15.00")
    assert breakdown[2].count == 1

    # Sum of percentages equals 100.00%
    total_pct = sum(b.percentage for b in breakdown)
    assert total_pct == Decimal("100.00")
