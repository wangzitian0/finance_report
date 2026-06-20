"""``Quantity`` — the authoritative shares/units/contracts value type."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from common.quantity.errors import FloatNotAllowedError, UnitMismatchError
from common.quantity.unit import Unit
from common.ratio import Ratio

QUANTITY_DP: int = 6
QUANTITY_QUANTUM = Decimal("0.000001")
QUANTITY_ROUNDING: str = ROUND_HALF_UP

_QuantityInput = Decimal | int


def _coerce(value: object, what: str = "quantity value") -> Decimal:
    if isinstance(value, bool):
        raise FloatNotAllowedError(f"bool is not a valid {what}")
    if isinstance(value, float):
        raise FloatNotAllowedError(
            f"float is not allowed for {what} (IEEE-754 precision loss); use Decimal"
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise FloatNotAllowedError(f"{what} must be finite")
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise FloatNotAllowedError(
        f"{what} must be Decimal or int, got {type(value).__name__}"
    )


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
        return Quantity(
            self.value.quantize(QUANTITY_QUANTUM, rounding=rounding), self.unit
        )

    def _require_same_unit(self, other: Quantity, op: str) -> None:
        if not isinstance(other, Quantity):
            raise TypeError(f"cannot {op} Quantity and {type(other).__name__}")
        if self.unit != other.unit:
            raise UnitMismatchError(
                f"cannot {op} across units: {self.unit.code} and {other.unit.code}"
            )

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
        # Scale by a dimensionless Decimal/int factor. float/bool stay a hard red
        # line (raise); any other type yields NotImplemented so a reflected
        # operand can handle it — e.g. quantity * UnitPrice -> Money.
        if isinstance(factor, (Decimal, int)) and not isinstance(factor, bool):
            return Quantity(self.value * factor, self.unit)
        if isinstance(factor, (bool, float)):
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
