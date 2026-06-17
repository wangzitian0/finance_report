"""Canonical monetary rounding policy.

Currency amounts are quantized to 2 decimal places using banker's rounding
(``ROUND_HALF_EVEN``). This is the single source of truth for money rounding;
see ``docs/ssot/accounting.md#decimal-rule``.

This is the backend's runtime money rounding (the backend's shippable "end" of the
cross-language standard, #1171); ``apps/backend/src/utils/money.py`` re-exports
``to_money``/``MONEY_QUANTUM`` from here. It mirrors the reference impl in
``common/money`` — kept identical by the shared conformance vectors — because
``common/`` is not shipped into the backend image.

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
