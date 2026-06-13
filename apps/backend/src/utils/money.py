"""Canonical monetary rounding policy.

Currency amounts are quantized to 2 decimal places using banker's rounding
(``ROUND_HALF_EVEN``). This is the single source of truth for money rounding;
see ``docs/ssot/accounting.md#decimal-rule``.

Out of scope (deliberately use their own quantization):
- FX rates and security prices: 6 dp (``services/market_data.py``).
- Share quantities: 6 dp (``services/investment_accounting.py``).
- Percentages / performance ratios (XIRR, TWR, MWR, allocation %): not currency.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

# 2-decimal-place currency quantum.
MONEY_QUANTUM: Decimal = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    """Quantize a Decimal currency amount to 2 dp using banker's rounding.

    Banker's rounding (round-half-to-even) is the project-wide canonical policy
    for currency amounts. Pass a ``Decimal`` (never ``float`` — see the decimal
    rule in the accounting SSOT).
    """
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
