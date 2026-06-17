"""``Ratio`` — the authoritative dimensionless-ratio value type.

A ratio is a unitless ``Decimal`` (e.g. ``Decimal("0.125")`` == 12.5%). It is the
base element for performance ratios (return-on-cost, XIRR/TWR/MWR), allocation
shares, and confidence proportions — everything that was previously ad-hoc
``value / total`` math with **inconsistent** percent rounding (HALF_UP in some
paths, HALF_EVEN in others).

The point, like ``Money``, is to make bad states unrepresentable and to give the
whole project ONE percent-display policy:

- construction rejects ``float`` (the numeric red line);
- ``fraction(part, whole)`` is the single primitive for building a ratio from two
  quantities (zero whole is undefined → raises);
- ``to_percent`` renders the percentage with the canonical **2 dp, ROUND_HALF_UP**
  policy (finance display convention) — the single standard both ends share.

Stored value is the *exact* Decimal; rounding happens only at the percent boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from common.ratio.errors import FloatNotAllowedError, UndefinedRatioError

# Canonical percent-display policy (NOT money's HALF_EVEN — percentages are not
# money and follow the finance display convention of round-half-up).
PERCENT_DP: int = 2
PERCENT_ROUNDING: str = ROUND_HALF_UP

_RatioInput = Decimal | int


def _coerce(value: object, what: str = "ratio value") -> Decimal:
    if isinstance(value, bool):
        raise FloatNotAllowedError(f"bool is not a valid {what}")
    if isinstance(value, float):
        raise FloatNotAllowedError(f"float is not allowed for {what} (IEEE-754 precision loss); use Decimal")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise FloatNotAllowedError(f"{what} must be Decimal or int, got {type(value).__name__}")


@dataclass(frozen=True)
class Ratio:
    """An immutable dimensionless ratio (``0.125`` == 12.5%).

    >>> Ratio.fraction(1, 8).to_percent()
    Decimal('12.50')
    """

    value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _coerce(self.value))

    # ── construction ────────────────────────────────────────────────────
    @classmethod
    def fraction(cls, part: _RatioInput, whole: _RatioInput) -> Ratio:
        """Build a ratio ``part / whole``. A zero whole is undefined and raises."""
        p = _coerce(part, "part")
        w = _coerce(whole, "whole")
        if w == 0:
            raise UndefinedRatioError("ratio is undefined for a zero whole")
        return cls(p / w)

    @classmethod
    def zero(cls) -> Ratio:
        return cls(Decimal("0"))

    @classmethod
    def from_percent(cls, percent: _RatioInput) -> Ratio:
        """Build a ratio from a percentage number (``12.5`` -> ``0.125``)."""
        return cls(_coerce(percent, "percent") / Decimal("100"))

    # ── percent rendering (the single shared standard) ──────────────────
    def to_percent(self, dp: int = PERCENT_DP, rounding: str = PERCENT_ROUNDING) -> Decimal:
        """Return the percentage value quantized to ``dp`` (default 2 dp, HALF_UP)."""
        quantum = Decimal(1).scaleb(-dp)  # 10**-dp, e.g. dp=2 -> 0.01
        return (self.value * Decimal("100")).quantize(quantum, rounding=rounding)

    def format_percent(self, dp: int = PERCENT_DP) -> str:
        """Render as a ``"12.50%"`` string at the canonical policy."""
        return f"{self.to_percent(dp)}%"

    # ── dimensionless arithmetic (ratios share one implicit unit) ───────
    def __add__(self, other: Ratio) -> Ratio:
        return Ratio(self.value + _as_ratio(other).value)

    def __sub__(self, other: Ratio) -> Ratio:
        return Ratio(self.value - _as_ratio(other).value)

    def __neg__(self) -> Ratio:
        return Ratio(-self.value)

    def __mul__(self, factor: _RatioInput) -> Ratio:
        return Ratio(self.value * _coerce(factor, "factor"))

    __rmul__ = __mul__

    def __lt__(self, other: Ratio) -> bool:
        return self.value < _as_ratio(other).value

    def __le__(self, other: Ratio) -> bool:
        return self.value <= _as_ratio(other).value

    def __gt__(self, other: Ratio) -> bool:
        return self.value > _as_ratio(other).value

    def __ge__(self, other: Ratio) -> bool:
        return self.value >= _as_ratio(other).value

    def __str__(self) -> str:
        return self.format_percent()


def _as_ratio(other: object) -> Ratio:
    if not isinstance(other, Ratio):
        raise TypeError(f"expected a Ratio, got {type(other).__name__}")
    return other
