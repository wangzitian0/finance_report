"""Backend runtime money value types — the backend's "end" of the money standard.

Single-source Python money value types (#2752), bridged to ``common.audit.money``
for tools/tests and aligned with ``apps/frontend/src/lib/audit/money`` via
``common/audit/money/conformance/vectors.json`` (executed by frontend
Vitest conformance specs; backend unit assertions in
``apps/backend/tests/audit/money/``).

Contract: ``common/audit/money/readme.md#money-type``.
"""

from __future__ import annotations

from src.audit.money.balances import CurrencyBalance, CurrencyBalances
from src.audit.money.convert import convert
from src.audit.money.currency import ISO_4217_CODES, Currency
from src.audit.money.errors import (
    CurrencyMismatchError,
    FloatNotAllowedError,
    InvalidCurrencyError,
    InvalidExchangeRateError,
    MoneyError,
)
from src.audit.money.exchange_rate import ExchangeRate
from src.audit.money.money import Money
from src.audit.money.rounding import MONEY_QUANTUM, to_money

__all__ = [
    "ISO_4217_CODES",
    "MONEY_QUANTUM",
    "Currency",
    "CurrencyBalance",
    "CurrencyBalances",
    "CurrencyMismatchError",
    "ExchangeRate",
    "FloatNotAllowedError",
    "InvalidExchangeRateError",
    "InvalidCurrencyError",
    "Money",
    "MoneyError",
    "convert",
    "to_money",
]
