"""The single FX conversion primitive.

Every cross-currency restatement (base-currency reporting, FX legs, …) routes
through :func:`convert`. Centralising it means rounding and rate handling are
defined in exactly one place: a Decimal rate, an explicit target currency, and
the canonical banker's rounding applied at the boundary.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from common.money.currency import Currency
from common.money.errors import FloatNotAllowedError
from common.money.money import Money


def convert(
    money: Money,
    rate: Decimal | int,
    *,
    to: Currency | str,
    rounding: str = ROUND_HALF_EVEN,
) -> Money:
    """Convert ``money`` into the ``to`` currency at ``rate``.

    ``rate`` is expressed as *target per source* (``amount_to = amount_from *
    rate``) and must be a ``Decimal`` (or ``int``) — never a ``float``. The
    result is quantized to the 2-dp money quantum using ``rounding`` (banker's
    rounding by default). A round-trip ``convert(convert(m, r, to=B), 1/r,
    to=A)`` returns the original amount up to that 2-dp boundary.
    """
    if isinstance(rate, bool) or isinstance(rate, float):
        raise FloatNotAllowedError("FX rate must be Decimal or int, not float/bool")
    if not isinstance(rate, (Decimal, int)):
        raise FloatNotAllowedError(
            f"FX rate must be Decimal or int, got {type(rate).__name__}"
        )
    target = Currency.of(to)
    converted = money.amount * Decimal(rate)
    return Money(converted, target).quantize(rounding=rounding)
