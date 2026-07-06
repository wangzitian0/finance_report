"""``src.audit`` — the number-governor's flat value-object surface.

Re-exports the 10 Shared-Kernel value-object classes (``common/audit/contract.py``'s
``units``) flat at the package root, so a consumer that only needs the class can
write ``from src.audit import Money``. Each domain's errors, wire codecs, and
helper functions are mostly NOT re-exported here (several names collide across
domains, e.g. ``FloatNotAllowedError`` is defined independently in every domain)
— reach those via the domain submodule instead: ``from src.audit.money import
FloatNotAllowedError, money_to_wire``. The six collision-free helpers other
PACKAGES consume (``to_money`` / ``balance_check`` / ``normalize_currency_code``
/ ``InvalidCurrencyError`` / ``convert`` / ``MoneyError``) ARE published,
because the cross-package rule requires every cross-domain-imported name to be
in this ``__all__`` (#1421, #1610).
"""

from __future__ import annotations

from src.audit.money import (
    Currency,
    CurrencyBalance,
    CurrencyBalances,
    ExchangeRate,
    Money,
    MoneyTolerance,
)
from src.audit.money.adopt import balance_check
from src.audit.money.convert import convert
from src.audit.money.currency import normalize_currency_code
from src.audit.money.errors import InvalidCurrencyError, MoneyError
from src.audit.money.rounding import to_money
from src.audit.quantity import Quantity, Unit
from src.audit.ratio import Ratio
from src.audit.unit_price import UnitPrice

__all__ = [
    "CurrencyBalance",
    "CurrencyBalances",
    "Currency",
    "InvalidCurrencyError",
    "MoneyError",
    "balance_check",
    "convert",
    "normalize_currency_code",
    "to_money",
    "ExchangeRate",
    "Money",
    "MoneyTolerance",
    "Quantity",
    "Ratio",
    "Unit",
    "UnitPrice",
]
