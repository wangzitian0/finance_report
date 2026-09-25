"""Pure calculation core for Cash Flow bridge reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.audit.money import to_money


@dataclass(frozen=True)
class CashFlowBridgeTotals:
    """Immutable calculation outcome of a cash flow bridge evaluation."""

    operating_total: Decimal
    investing_total: Decimal
    financing_total: Decimal
    classified_activity: Decimal
    cash_delta: Decimal
    net_cash_flow: Decimal
    fx_effect: Decimal
    bridge_total: Decimal
    discrepancy: Decimal
    reconciles: bool


def calculate_cash_flow_bridge(
    *,
    beginning_cash: Decimal,
    ending_cash: Decimal,
    operating_total: Decimal,
    investing_total: Decimal,
    financing_total: Decimal,
    unclassified_cash: Decimal = Decimal("0.00"),
    opening_stock_adjustment: Decimal = Decimal("0.00"),
    fx_effect: Decimal = Decimal("0.00"),
) -> CashFlowBridgeTotals:
    """Calculate authoritative cash flow movement and reconciliation bridge."""
    classified_activity = to_money(operating_total + investing_total + financing_total)
    cash_delta = to_money(ending_cash - beginning_cash)
    net_cash_flow = to_money(cash_delta - opening_stock_adjustment)
    quantized_fx_effect = to_money(fx_effect)

    bridge_total = to_money(classified_activity + unclassified_cash + quantized_fx_effect + opening_stock_adjustment)
    discrepancy = to_money(cash_delta - bridge_total)
    reconciles = discrepancy == Decimal("0.00")

    return CashFlowBridgeTotals(
        operating_total=to_money(operating_total),
        investing_total=to_money(investing_total),
        financing_total=to_money(financing_total),
        classified_activity=classified_activity,
        cash_delta=cash_delta,
        net_cash_flow=net_cash_flow,
        fx_effect=quantized_fx_effect,
        bridge_total=bridge_total,
        discrepancy=discrepancy,
        reconciles=reconciles,
    )
