"""``ledger.data`` — the account-balance read model (projection / leaf sink).

Computed FROM the posted write side; nothing in ``base/`` or ``extension/`` imports
this layer (the gate enforces ``data`` as a sink). Holds the signed account-balance
projections and the accounting-equation check derived from them.
"""

from __future__ import annotations

from src.ledger.data.balance import (
    calculate_account_balance,
    calculate_account_balances,
    verify_accounting_equation,
)

__all__ = [
    "calculate_account_balance",
    "calculate_account_balances",
    "verify_accounting_equation",
]
