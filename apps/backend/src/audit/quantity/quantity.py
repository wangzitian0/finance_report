"""``Quantity`` — the authoritative shares/units/contracts value type."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from src.audit.quantity.errors import FloatNotAllowedError, UnitMismatchError
from src.audit.quantity.unit import Unit
from src.audit.ratio import Ratio
from src.decimal_scalar import coerce_decimal

QUANTITY_DP: int = 6
QUANTITY_QUANTUM = Decimal("0.000001")
QUANTITY_ROUNDING: str = ROUND_HALF_UP

_QuantityInput = Decimal | int


def _coerce(value: object, what: str = "quantity value") -> Decimal:
    return coerce_decimal(value, what, float_error=FloatNotAllowedError, require_finite=True)


@dataclass(frozen=True)
class Quantity:
    """An immutable quantity in one unit."""

    value: Decimal
    unit: Unit

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _coerce(self.value))
        object.__setattr__(self, "unit", Unit.of(self.unit))

    @classmethod
    def zero(cls, unit: Unit | str) -> Quantity:
        return cls(Decimal("0"), unit)

    def is_zero(self) -> bool:
        return self.value.is_zero()

    def quantize(self, rounding: str = QUANTITY_ROUNDING) -> Quantity:
        return Quantity(self.value.quantize(QUANTITY_QUANTUM, rounding=rounding), self.unit)

    def _require_same_unit(self, other: Quantity, op: str) -> None:
        if not isinstance(other, Quantity):
            raise TypeError(f"cannot {op} Quantity and {type(other).__name__}")
        if self.unit != other.unit:
            raise UnitMismatchError(f"cannot {op} across units: {self.unit.code} and {other.unit.code}")

    def __add__(self, other: Quantity) -> Quantity:
        self._require_same_unit(other, "add")
        return Quantity(self.value + other.value, self.unit)

    def __sub__(self, other: Quantity) -> Quantity:
        self._require_same_unit(other, "subtract")
        return Quantity(self.value - other.value, self.unit)

    def __neg__(self) -> Quantity:
        return Quantity(-self.value, self.unit)

    def __abs__(self) -> Quantity:
        return Quantity(abs(self.value), self.unit)

    def __mul__(self, factor: _QuantityInput) -> Quantity:
        # Scale by a dimensionless factor, routed through _coerce so the value-type
        # invariants hold (finiteness check; float/bool stay a hard red line).
        # Any other operand type yields NotImplemented so a reflected op can handle
        # it — e.g. quantity * UnitPrice -> Money.
        if isinstance(factor, Decimal | int | float):  # bool is an int subclass
            return Quantity(self.value * _coerce(factor, "factor"), self.unit)
        return NotImplemented

    __rmul__ = __mul__

    def __lt__(self, other: Quantity) -> bool:
        self._require_same_unit(other, "compare")
        return self.value < other.value

    def __le__(self, other: Quantity) -> bool:
        self._require_same_unit(other, "compare")
        return self.value <= other.value

    def __gt__(self, other: Quantity) -> bool:
        self._require_same_unit(other, "compare")
        return self.value > other.value

    def __ge__(self, other: Quantity) -> bool:
        self._require_same_unit(other, "compare")
        return self.value >= other.value

    def ratio_to(self, whole: Quantity) -> Ratio:
        self._require_same_unit(whole, "divide")
        return Ratio.fraction(self.value, whole.value)

    def __truediv__(self, other: Quantity) -> Ratio:
        return self.ratio_to(other)

    def __str__(self) -> str:
        return f"{self.value} {self.unit.code}"
