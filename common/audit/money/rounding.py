"""Canonical monetary rounding policy.

Currency amounts are quantized to 2 decimal places using banker's rounding
(``ROUND_HALF_EVEN``). This is the single source of truth for money rounding;
see ``common/ledger/readme.md#decimal-rule``.

This module is the canonical home for the cross-language standard, tooling and
tests (it lives in ``common/`` so every end shares one definition). The backend
keeps its **own** self-contained ``to_money`` in ``apps/backend/src/audit/money/``
for its runtime (``common/`` is not shipped into the image); the conformance
suite proves the two stay identical. Runtime unification waits on adoption (#1171).

Out of scope (deliberately use their own quantization):
- FX rates and security prices: 6 dp (``services/market_data/``).
- Share quantities: 6 dp (``portfolio/extension/accounting.py``).
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
