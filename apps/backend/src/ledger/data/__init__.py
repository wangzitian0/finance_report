"""``ledger.data`` — the account-balance read model (projection / leaf sink).

Computed FROM the posted write side; nothing in ``base/`` or ``extension/`` imports
this layer (the gate enforces ``data`` as a sink). Holds the signed account-balance
projections and the accounting-equation check derived from them.
"""

from __future__ import annotations

from src.ledger.data.account_coverage import (
    DEFAULT_STALE_AFTER_DAYS,
    StatementCoverageRow,
    get_account_statement_coverage,
    register_statement_coverage_reader,
)
from src.ledger.data.balance import (
    calculate_account_balance,
    calculate_account_balances,
    calculate_account_balances_in_base_currency,
    verify_accounting_equation,
)

__all__ = [
    "DEFAULT_STALE_AFTER_DAYS",
    "StatementCoverageRow",
    "calculate_account_balance",
    "calculate_account_balances",
    "calculate_account_balances_in_base_currency",
    "get_account_statement_coverage",
    "register_statement_coverage_reader",
    "verify_accounting_equation",
]
