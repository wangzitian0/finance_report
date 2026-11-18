from decimal import Decimal

import pytest

from src.portfolio.base.valuation_calculator import AllocationItem, PortfolioValuationTotals, PositionValuationResult, calculate_allocation_breakdown, calculate_portfolio_valuation_totals, calculate_position_valuation

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("qty", "cost", "price", "expected"),
    [
        ("100", "150.00", "175.50", (Decimal("17550.00"), Decimal("15000.00"), Decimal("2550.00"), Decimal("17.00"))),
        ("50", "200.00", "180.00", (Decimal("9000.00"), Decimal("10000.00"), Decimal("-1000.00"), Decimal("-10.00"))),
        ("0", "100.00", "120.00", (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))),
        ("10", "0.00", "50.00", (Decimal("500.00"), Decimal("0.00"), Decimal("500.00"), Decimal("0.00"))),
    ],
)
def test_calculate_position_valuation(qty, cost, price, expected):
    res = calculate_position_valuation(quantity=Decimal(qty), unit_cost_basis=Decimal(cost), market_price=Decimal(price))
    assert (isinstance(res, PositionValuationResult), res.market_value, res.cost_basis, res.unrealized_pnl, res.unrealized_pnl_percent) == (True, *expected)


@pytest.mark.parametrize(
    ("qty", "cost", "price", "match"),
    [("-10", "100.00", "120.00", "Quantity cannot be negative"), ("10", "100.00", "-5.00", "Market price cannot be negative"), ("10", "-100.00", "120.00", "Cost basis cannot be negative")],
)
def test_calculate_position_valuation_rejects_negative_inputs(qty, cost, price, match):
    with pytest.raises(ValueError, match=match):
        calculate_position_valuation(quantity=Decimal(qty), unit_cost_basis=Decimal(cost), market_price=Decimal(price))


def test_portfolio_totals_and_allocation_breakdown():
    positions = [calculate_position_valuation(quantity=Decimal(q), unit_cost_basis=Decimal(c), market_price=Decimal(p)) for q, c, p in (("100", "50.00", "70.00"), ("200", "100.00", "90.00"), ("50", "10.00", "15.00"))]
    totals, empty = calculate_portfolio_valuation_totals(positions), calculate_portfolio_valuation_totals([])
    breakdown = calculate_allocation_breakdown([AllocationItem(category=cat, value=Decimal(val)) for cat, val in (("Technology", "6000.00"), ("Finance", "3000.00"), ("Technology", "4000.00"), ("Healthcare", "7000.00"))])
    assert (
        isinstance(totals, PortfolioValuationTotals),
        (totals.total_market_value, totals.total_cost_basis, totals.total_unrealized_pnl, totals.total_unrealized_pnl_percent),
        (empty.total_market_value, empty.total_cost_basis, empty.total_unrealized_pnl, empty.total_unrealized_pnl_percent),
        [(b.category, b.value, b.percentage, b.count) for b in breakdown],
        sum(b.percentage for b in breakdown),
    ) == (
        True,
        (Decimal("25750.00"), Decimal("25500.00"), Decimal("250.00"), Decimal("0.98")),
        (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")),
        [("Technology", Decimal("10000.00"), Decimal("50.00"), 2), ("Healthcare", Decimal("7000.00"), Decimal("35.00"), 1), ("Finance", Decimal("3000.00"), Decimal("15.00"), 1)],
        Decimal("100.00"),
    )
