"""``common.audit.money`` — the project's money-primitives narrow waist.

One authoritative value type for money (:class:`Money`), a validated currency
code (:class:`Currency`), a single FX conversion primitive (:func:`convert`),
and a per-currency balance container (:class:`CurrencyBalances`) that makes a
multi-currency statement structurally inexpressible as a scalar.

Dependency-light (stdlib + dataclasses + Decimal only) so it is importable from
tooling, tests and the conformance suite. The canonical money rounding
(:func:`to_money`) also lives here; the backend keeps its own self-contained copy
for its runtime until adoption (#1171), and the conformance suite keeps the two
in lockstep.

Contract: ``common/audit/money/readme.md#money-type`` (#1167).
"""

from __future__ import annotations

from common.audit.money.balances import CurrencyBalance, CurrencyBalances
from common.audit.money.convert import convert
from common.audit.money.currency import ISO_4217_CODES, Currency
from common.audit.money.errors import (
    CurrencyMismatchError,
    FloatNotAllowedError,
    InvalidCurrencyError,
    InvalidExchangeRateError,
    InvalidMoneyPayloadError,
    MoneyError,
)
from common.audit.money.exchange_rate import ExchangeRate
from common.audit.money.money import Money
from common.audit.money.rounding import MONEY_QUANTUM, to_money
from common.audit.money.tolerance import MoneyTolerance
from common.audit.money.wire import (
    exchange_rate_from_db_fields,
    exchange_rate_from_wire,
    exchange_rate_to_db_fields,
    exchange_rate_to_wire,
    money_from_db_fields,
    money_from_wire,
    money_to_db_fields,
    money_to_wire,
)

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
    "InvalidMoneyPayloadError",
    "Money",
    "MoneyError",
    "MoneyTolerance",
    "convert",
    "exchange_rate_from_db_fields",
    "exchange_rate_from_wire",
    "exchange_rate_to_db_fields",
    "exchange_rate_to_wire",
    "money_from_db_fields",
    "money_from_wire",
    "money_to_db_fields",
    "money_to_wire",
    "to_money",
]
