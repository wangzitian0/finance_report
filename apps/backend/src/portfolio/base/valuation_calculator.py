"""AC-portfolio.valuation.1: Pure domain calculation core for portfolio valuation & asset allocation.

Zero-DB, zero-mock, pure Python Decimal mathematical reductions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.audit.money import to_money
from src.audit.ratio import Ratio


@dataclass(frozen=True)
class PositionValuationResult:
    """Valuation result for a single position."""

    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_percent: Decimal


@dataclass(frozen=True)
class PortfolioValuationTotals:
    """Aggregate totals across all portfolio positions."""

    total_market_value: Decimal
    total_cost_basis: Decimal
    total_unrealized_pnl: Decimal
    total_unrealized_pnl_percent: Decimal


@dataclass(frozen=True)
class AllocationItem:
    """Generic category value pair for portfolio breakdowns."""

    category: str
    value: Decimal


@dataclass(frozen=True)
class AllocationBreakdownResult:
    """Calculated allocation share for a single category."""

    category: str
    value: Decimal
    percentage: Decimal
    count: int


def calculate_position_valuation(
    *,
    quantity: Decimal,
    unit_cost_basis: Decimal,
    market_price: Decimal,
) -> PositionValuationResult:
    """Calculate market value, cost basis, and unrealized PnL for a position."""
    if quantity < Decimal("0"):
        raise ValueError("Quantity cannot be negative")
    if market_price < Decimal("0"):
        raise ValueError("Market price cannot be negative")
    if unit_cost_basis < Decimal("0"):
        raise ValueError("Cost basis cannot be negative")

    market_value = to_money(quantity * market_price)
    cost_basis = to_money(quantity * unit_cost_basis)
    unrealized_pnl = to_money(market_value - cost_basis)
    ratio = Ratio.fraction_or_zero(unrealized_pnl, cost_basis)

    return PositionValuationResult(
        market_value=market_value,
        cost_basis=cost_basis,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_percent=ratio.to_percent(),
    )


def calculate_portfolio_valuation_totals(
    positions: Sequence[PositionValuationResult],
) -> PortfolioValuationTotals:
    """Aggregate totals and net unrealized PnL percentage across all positions."""
    total_market_value = to_money(sum((p.market_value for p in positions), Decimal("0.00")))
    total_cost_basis = to_money(sum((p.cost_basis for p in positions), Decimal("0.00")))
    total_unrealized_pnl = to_money(sum((p.unrealized_pnl for p in positions), Decimal("0.00")))
    total_ratio = Ratio.fraction_or_zero(total_unrealized_pnl, total_cost_basis)

    return PortfolioValuationTotals(
        total_market_value=total_market_value,
        total_cost_basis=total_cost_basis,
        total_unrealized_pnl=total_unrealized_pnl,
        total_unrealized_pnl_percent=total_ratio.to_percent(),
    )


def calculate_allocation_breakdown(
    items: Sequence[AllocationItem],
) -> list[AllocationBreakdownResult]:
    """Group items by category, calculate percentage of total value, and sort descending."""
    category_values: dict[str, Decimal] = {}
    category_counts: dict[str, int] = {}
    total_value = Decimal("0.00")

    for item in items:
        cat = item.category or "Unknown"
        category_values[cat] = category_values.get(cat, Decimal("0.00")) + item.value
        category_counts[cat] = category_counts.get(cat, 0) + 1
        total_value += item.value

    results = []
    for cat, val in category_values.items():
        ratio = Ratio.fraction_or_zero(val, total_value)
        results.append(
            AllocationBreakdownResult(
                category=cat,
                value=to_money(val),
                percentage=ratio.to_percent(),
                count=category_counts[cat],
            )
        )

    results.sort(key=lambda x: x.value, reverse=True)
    return results
