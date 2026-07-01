"""Byte-identical adoption helpers for routing hot paths through Money (#1171).

The reconciliation and reporting hot paths must keep producing **byte-identical**
totals while being routed through the money value types. Two realities make a
naive swap unsafe, so these helpers exist:

1. ``Money``/``Currency`` validate ISO-4217 strictly, but those paths legitimately
   carry the reconciliation ``"*"`` sentinel and (for FX) currencies outside the
   active ISO set. So each helper routes through ``Money``/``convert`` **only when
   both currencies are valid ISO codes**, and otherwise falls back to the *exact
   same* Decimal arithmetic the call-site used before — byte-identical for every
   input, ISO or not.
2. Aggregations sum **unquantized** products and quantize the total once. Routing
   per-term through ``convert`` (which quantizes each term) would change the total.
   :func:`restate_unrounded` therefore does not quantize; :func:`restate` is for
   the single-shot conversions that already quantized.

Every helper returns a ``Decimal`` so call-sites are a drop-in replacement.
"""

from __future__ import annotations

from decimal import Decimal

from src.audit.money.convert import convert
from src.audit.money.currency import Currency
from src.audit.money.errors import InvalidCurrencyError
from src.audit.money.exchange_rate import ExchangeRate
from src.audit.money.money import Money
from src.audit.money.rounding import to_money


def _iso(*codes: str | None) -> bool:
    """True iff every code is a valid ISO-4217 currency (so Money can carry it)."""
    try:
        for code in codes:
            if code is None:
                return False
            Currency(code)
        return True
    except InvalidCurrencyError:
        return False


def restate(amount: Decimal, from_ccy: str, rate: Decimal, to_ccy: str) -> Decimal:
    """Convert ``amount`` (``from_ccy``) into ``to_ccy`` at ``rate``, quantized 2 dp.

    Byte-identical to the legacy ``to_money(amount * rate)``: for ISO currencies it
    routes through the single :func:`convert` FX primitive (same banker's rounding
    at the boundary); otherwise it falls back to that exact Decimal computation.
    """
    if _iso(from_ccy, to_ccy):
        return convert(Money(amount, from_ccy), ExchangeRate(from_ccy, to_ccy, rate)).amount
    return to_money(amount * Decimal(rate))


def restate_unrounded(amount: Decimal, from_ccy: str, rate: Decimal, to_ccy: str) -> Decimal:
    """Restate ``amount`` (``from_ccy``) into ``to_ccy`` at ``rate``, **unquantized**.

    For aggregations that sum products and quantize the total once. Byte-identical
    to the legacy ``Decimal(str(amount)) * rate``: for ISO currencies it builds a
    typed, currency-correct ``Money`` in the target; otherwise identical Decimal.
    """
    product = Decimal(str(amount)) * rate
    if _iso(from_ccy, to_ccy):
        return Money(product, to_ccy).amount
    return product


def balance_check(
    opening: Decimal | None,
    closing: Decimal | None,
    net_transactions: Decimal | None,
    currency: str | None = None,
) -> tuple[Decimal, Decimal]:
    """Return ``(expected_closing, diff)`` for a single currency's balance loop.

    ``expected_closing = opening + net``; ``diff = abs(closing - expected)``. For a
    valid ISO ``currency`` the arithmetic runs through same-currency ``Money`` (so a
    cross-currency mix is structurally impossible); for the ``"*"`` sentinel / a
    non-ISO code it uses the identical Decimal arithmetic. Byte-identical either way.
    """
    op = opening or Decimal("0")
    nt = net_transactions or Decimal("0")
    cl = closing or Decimal("0")
    if _iso(currency):
        expected = (Money(op, currency) + Money(nt, currency)).amount
        diff = abs((Money(cl, currency) - Money(expected, currency)).amount)
        return expected, diff
    expected = op + nt
    return expected, abs(cl - expected)
