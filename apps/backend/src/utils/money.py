"""Canonical monetary rounding policy (backward-compatible re-export).

The backend money value types + rounding now live in :mod:`src.money` (the
backend's shippable "end" of the cross-language money standard, #1167). This
module re-exports them so existing ``from src.utils.money import to_money`` /
``MONEY_QUANTUM`` imports keep working.

See ``docs/ssot/accounting.md#decimal-rule`` and ``#money-type``.

Out of scope (deliberately use their own quantization):
- FX rates and security prices: 6 dp (``services/market_data.py``).
- Share quantities: 6 dp (``services/investment_accounting.py``).
- Percentages / performance ratios (XIRR, TWR, MWR, allocation %): not currency.
"""

from __future__ import annotations

from src.money import (
    MONEY_QUANTUM,
    Currency,
    CurrencyBalance,
    CurrencyBalances,
    Money,
    convert,
    to_money,
)

__all__ = [
    "MONEY_QUANTUM",
    "Currency",
    "CurrencyBalance",
    "CurrencyBalances",
    "Money",
    "convert",
    "to_money",
]
