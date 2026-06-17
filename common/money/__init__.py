"""``common.money`` — the project's money-primitives narrow waist.

One authoritative value type for money (:class:`Money`), a validated currency
code (:class:`Currency`), a single FX conversion primitive (:func:`convert`),
and a per-currency balance container (:class:`CurrencyBalances`) that makes a
multi-currency statement structurally inexpressible as a scalar.

Dependency-light (stdlib + dataclasses + Decimal only) so it is importable from
tooling, tests and the conformance suite. The canonical money rounding
(:func:`to_money`) also lives here; the backend keeps its own self-contained copy
for its runtime until adoption (#1171), and the conformance suite keeps the two
in lockstep.

Contract: ``docs/ssot/accounting.md#money-type`` (#1167).
"""

from __future__ import annotations

from common.money.balances import CurrencyBalance, CurrencyBalances
from common.money.convert import convert
from common.money.currency import ISO_4217_CODES, Currency
from common.money.errors import (
    CurrencyMismatchError,
    FloatNotAllowedError,
    InvalidCurrencyError,
    MoneyError,
)
from common.money.money import Money
from common.money.rounding import MONEY_QUANTUM, to_money

__all__ = [
    "ISO_4217_CODES",
    "MONEY_QUANTUM",
    "Currency",
    "CurrencyBalance",
    "CurrencyBalances",
    "CurrencyMismatchError",
    "FloatNotAllowedError",
    "InvalidCurrencyError",
    "Money",
    "MoneyError",
    "convert",
    "to_money",
]
