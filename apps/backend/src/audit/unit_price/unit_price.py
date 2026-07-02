"""``UnitPrice`` — money-per-quantity composite value type (mirrors common/audit/unit_price).

Backend runtime copy: identical semantics to ``common/audit/unit_price/unit_price.py``,
importing the shipped ``src.audit.money`` / ``src.audit.quantity`` types. The conformance
suite proves the two stay identical (``common/`` is not shipped into the image).
See ``common/audit/readme.md#base-packages``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from src.audit.decimal_scalar import coerce_decimal
from src.audit.money.currency import Currency
from src.audit.money.money import Money
from src.audit.quantity.quantity import Quantity
from src.audit.quantity.unit import Unit
from src.audit.unit_price.errors import (
    CurrencyMismatchError,
    FloatNotAllowedError,
    UndefinedUnitPriceError,
    UnitMismatchError,
)

# Price/unit-rate quantum: 6 dp, ROUND_HALF_UP. Deliberately NOT the 2-dp money
# quantum — prices and unit costs carry sub-cent precision.
UNIT_PRICE_DP: int = 6
UNIT_PRICE_QUANTUM = Decimal("0.000001")
UNIT_PRICE_ROUNDING: str = ROUND_HALF_UP

_RateInput = Decimal | int


def _coerce_rate(value: object) -> Decimal:
    return coerce_decimal(value, "unit-price rate", float_error=FloatNotAllowedError, require_finite=True)


@dataclass(frozen=True)
class UnitPrice:
    """An immutable money-per-unit rate (a price/unit cost)."""

    rate: Decimal
    currency: Currency
    unit: Unit

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", _coerce_rate(self.rate))
        object.__setattr__(self, "currency", Currency.of(self.currency))
        object.__setattr__(self, "unit", Unit.of(self.unit))

    @classmethod
    def zero(cls, currency: Currency | str, unit: Unit | str) -> UnitPrice:
        return cls(Decimal("0"), currency, unit)

    @classmethod
    def from_total(cls, total: Money, quantity: Quantity) -> UnitPrice:
        if not isinstance(total, Money):
            raise TypeError(f"UnitPrice.from_total expects Money total, got {type(total).__name__}")
        if not isinstance(quantity, Quantity):
            raise TypeError(f"UnitPrice.from_total expects Quantity, got {type(quantity).__name__}")
        if quantity.value.is_zero():
            raise UndefinedUnitPriceError("cannot derive a unit price from zero quantity")
        return cls(total.amount / quantity.value, total.currency, quantity.unit)

    def is_zero(self) -> bool:
        return self.rate.is_zero()

    def quantize(self, rounding: str = UNIT_PRICE_ROUNDING) -> UnitPrice:
        return UnitPrice(
            self.rate.quantize(UNIT_PRICE_QUANTUM, rounding=rounding),
            self.currency,
            self.unit,
        )

    def __mul__(self, quantity: Quantity) -> Money:
        if not isinstance(quantity, Quantity):
            raise TypeError(f"UnitPrice can only be multiplied by a Quantity, got {type(quantity).__name__}")
        if self.unit != quantity.unit:
            raise UnitMismatchError(f"cannot price a {quantity.unit.code} quantity with a {self.unit.code} unit price")
        return Money(self.rate * quantity.value, self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> UnitPrice:
        return UnitPrice(-self.rate, self.currency, self.unit)

    def __abs__(self) -> UnitPrice:
        return UnitPrice(abs(self.rate), self.currency, self.unit)

    def _require_same_kind(self, other: UnitPrice, op: str) -> None:
        if not isinstance(other, UnitPrice):
            raise TypeError(f"cannot {op} UnitPrice and {type(other).__name__}")
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"cannot {op} across currencies: {self.currency.code} and {other.currency.code}"
            )
        if self.unit != other.unit:
            raise UnitMismatchError(f"cannot {op} across units: {self.unit.code} and {other.unit.code}")

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
