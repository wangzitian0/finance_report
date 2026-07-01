"""The single FX conversion primitive.

Every cross-currency restatement (base-currency reporting, FX legs, …) routes
through :func:`convert`. Centralising it means rounding and rate handling are
defined in exactly one place: a Decimal rate, an explicit target currency, and
the canonical banker's rounding applied at the boundary.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN

from src.audit.money.errors import CurrencyMismatchError, FloatNotAllowedError
from src.audit.money.exchange_rate import ExchangeRate
from src.audit.money.money import Money


def convert(
    money: Money,
    rate: ExchangeRate,
    rounding: str = ROUND_HALF_EVEN,
) -> Money:
    """Convert ``money`` into the ``to`` currency at ``rate``.

    ``rate`` is directed: ``amount_quote = amount_base * rate``. Its base
    currency must match ``money.currency``; the result is quantized to the 2-dp
    money quantum using ``rounding`` (banker's rounding by default).
    """
    if not isinstance(rate, ExchangeRate):
        raise FloatNotAllowedError(f"convert rate must be ExchangeRate, got {type(rate).__name__}")
    if money.currency != rate.base:
        raise CurrencyMismatchError(
            f"cannot convert {money.currency.code} with {rate.base.code}/{rate.quote.code} rate"
        )
    return Money(money.amount * rate.rate, rate.quote).quantize(rounding=rounding)
