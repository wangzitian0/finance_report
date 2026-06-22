"""``UnitPrice`` — the authoritative money-per-quantity composite value type.

A unit price is *money per one unit of a quantity* (a share price, a unit cost,
a per-contract rate). It is the composite that kept reappearing as raw
``Decimal`` glue at portfolio/market-data call sites — ``quantity.value * price``
to get an amount, ``amount / quantity.value`` to get a rate, plus a local 6-dp
``quantize`` helper duplicated per service. ``UnitPrice`` owns that semantics so
the glue and the duplicated quantum disappear.

Design (mirrors :class:`common.money.Money` / :class:`common.quantity.Quantity`):

- construction rejects ``float``/``bool`` (the standing monetary red line);
- a unit price carries **both** a :class:`~common.money.currency.Currency` and a
  :class:`~common.quantity.unit.Unit`, so applying it to a quantity yields
  :class:`~common.money.money.Money` in the right currency only when the units
  agree;
- the exact rate is stored; rounding happens only via :meth:`quantize` (6 dp,
  ``ROUND_HALF_UP`` — the price/unit-rate quantum, not the 2-dp money quantum).

Algebra:

- ``unit_price * quantity -> Money`` (the product of a quantity and its unit
  price); written price-first because :class:`Quantity` deliberately rejects
  non-scalar right-multiplication to protect the float red line.
- ``UnitPrice.from_total(money, quantity) -> UnitPrice`` (``Money / Quantity``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from common.decimal_scalar import coerce_decimal
from common.money.currency import Currency
from common.money.money import Money
from common.quantity.quantity import Quantity
from common.quantity.unit import Unit
from common.unit_price.errors import (
    CurrencyMismatchError,
    FloatNotAllowedError,
    UndefinedUnitPriceError,
    UnitMismatchError,
)

# Price/unit-rate quantum: 6 dp, ROUND_HALF_UP. Deliberately NOT the 2-dp money
# quantum — prices and unit costs carry sub-cent precision (see the rounding
# carve-out in common/money/rounding.py and docs/ssot/base-packages.md).
UNIT_PRICE_DP: int = 6
UNIT_PRICE_QUANTUM = Decimal("0.000001")
UNIT_PRICE_ROUNDING: str = ROUND_HALF_UP

_RateInput = Decimal | int


def _coerce_rate(value: object) -> Decimal:
    return coerce_decimal(
        value, "unit-price rate", float_error=FloatNotAllowedError, require_finite=True
    )


@dataclass(frozen=True)
class UnitPrice:
    """An immutable money-per-unit rate (a price/unit cost).

    >>> UnitPrice(Decimal("10.50"), "SGD", "shares") * Quantity(Decimal("3"), "shares")
    Money(amount=Decimal('31.50'), currency=Currency(code='SGD'))
    """

    rate: Decimal
    currency: Currency
    unit: Unit

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", _coerce_rate(self.rate))
        object.__setattr__(self, "currency", Currency.of(self.currency))
        object.__setattr__(self, "unit", Unit.of(self.unit))

    # ── construction helpers ────────────────────────────────────────────
    @classmethod
    def zero(cls, currency: Currency | str, unit: Unit | str) -> UnitPrice:
        return cls(Decimal("0"), currency, unit)

    @classmethod
    def from_total(cls, total: Money, quantity: Quantity) -> UnitPrice:
        """Derive ``Money / Quantity`` — a total spread over a quantity.

        The result keeps the total's currency and the quantity's unit. A zero
        quantity is undefined and raises :class:`UndefinedUnitPriceError`.
        """
        if not isinstance(total, Money):
            raise TypeError(
                f"UnitPrice.from_total expects Money total, got {type(total).__name__}"
            )
        if not isinstance(quantity, Quantity):
            raise TypeError(
                f"UnitPrice.from_total expects Quantity, got {type(quantity).__name__}"
            )
        if quantity.value.is_zero():
            raise UndefinedUnitPriceError(
                "cannot derive a unit price from zero quantity"
            )
        return cls(total.amount / quantity.value, total.currency, quantity.unit)

    def is_zero(self) -> bool:
        return self.rate.is_zero()

    # ── rounding ────────────────────────────────────────────────────────
    def quantize(self, rounding: str = UNIT_PRICE_ROUNDING) -> UnitPrice:
        return UnitPrice(
            self.rate.quantize(UNIT_PRICE_QUANTUM, rounding=rounding),
            self.currency,
            self.unit,
        )

    # ── apply to a quantity → Money ─────────────────────────────────────
    def __mul__(self, quantity: Quantity) -> Money:
        """``unit_price * quantity`` — extend a quantity at this price into Money.

        The quantity's unit must match this price's unit. The amount is exact
        (unquantized); apply :meth:`Money.quantize` at the money boundary.
        """
        if not isinstance(quantity, Quantity):
            raise TypeError(
                "UnitPrice can only be multiplied by a Quantity, got "
                f"{type(quantity).__name__}"
            )
        if self.unit != quantity.unit:
            raise UnitMismatchError(
                f"cannot price a {quantity.unit.code} quantity with a "
                f"{self.unit.code} unit price"
            )
        return Money(self.rate * quantity.value, self.currency)

    __rmul__ = __mul__

    # ── same currency+unit helpers ──────────────────────────────────────
    def __neg__(self) -> UnitPrice:
        return UnitPrice(-self.rate, self.currency, self.unit)

    def __abs__(self) -> UnitPrice:
        return UnitPrice(abs(self.rate), self.currency, self.unit)

    def _require_same_kind(self, other: UnitPrice, op: str) -> None:
        if not isinstance(other, UnitPrice):
            raise TypeError(f"cannot {op} UnitPrice and {type(other).__name__}")
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"cannot {op} across currencies: {self.currency.code} and "
                f"{other.currency.code}"
            )
        if self.unit != other.unit:
            raise UnitMismatchError(
                f"cannot {op} across units: {self.unit.code} and {other.unit.code}"
            )

    def __lt__(self, other: UnitPrice) -> bool:
        self._require_same_kind(other, "compare")
        return self.rate < other.rate

    def __le__(self, other: UnitPrice) -> bool:
        self._require_same_kind(other, "compare")
        return self.rate <= other.rate

    def __gt__(self, other: UnitPrice) -> bool:
        self._require_same_kind(other, "compare")
        return self.rate > other.rate

    def __ge__(self, other: UnitPrice) -> bool:
        self._require_same_kind(other, "compare")
        return self.rate >= other.rate

    def __str__(self) -> str:
        return f"{self.rate} {self.currency.code}/{self.unit.code}"
