"""Backend runtime money value types — the backend's "end" of the money standard.

Mirrors ``common/money`` (the reference impl) as a **self-contained, shippable**
module: the backend image does not ship ``common/``, so the backend is treated as
its own conformant end — exactly like the frontend has ``apps/frontend/src/lib/money``
(#1167). It is kept in lockstep with the reference impl by the shared conformance
vectors (``common/money/conformance/vectors.json``, asserted in
``tests/accounting/test_money_backend_module.py``) and the narrow-waist guard (#1172).

Contract: ``docs/ssot/accounting.md#money-type``.
"""

from __future__ import annotations

from src.money.balances import CurrencyBalance, CurrencyBalances
from src.money.convert import convert
from src.money.currency import ISO_4217_CODES, Currency
from src.money.errors import (
    CurrencyMismatchError,
    FloatNotAllowedError,
    InvalidCurrencyError,
    InvalidExchangeRateError,
    MoneyError,
)
from src.money.exchange_rate import ExchangeRate
from src.money.money import Money
from src.money.rounding import MONEY_QUANTUM, to_money

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
