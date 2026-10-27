"""Byte-identical adoption helper for routing a hot path through Money (#1171).

The reconciliation balance loop must keep producing **byte-identical** totals while
being routed through the money value types. ``Money``/``Currency`` validate ISO-4217
strictly, but that path legitimately carries the reconciliation ``"*"`` sentinel and
currencies outside the active ISO set. So :func:`balance_check` routes through ``Money``
**only when the currency is a valid ISO code**, and otherwise falls back to the *exact
same* Decimal arithmetic the call-site used before — byte-identical for every input,
ISO or not.

The helper returns ``Decimal`` values so call-sites are a drop-in replacement.
"""

from __future__ import annotations

from decimal import Decimal

from src.audit.money.currency import Currency
from src.audit.money.errors import InvalidCurrencyError
from src.audit.money.money import Money


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
