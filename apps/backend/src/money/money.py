"""``Money`` — the authoritative money value type (Decimal amount + Currency).

Immutable, Decimal-backed, and currency-aware. The point is to make bad money
states *unrepresentable*:

- construction rejects ``float`` (the standing monetary red line);
- arithmetic is allowed only **within one currency** — cross-currency ``+``/``-``
  or comparison raises :class:`CurrencyMismatchError` instead of silently
  summing across currencies. Cross-currency math must route through the single
  :func:`common.money.convert` primitive.

Scope note: ``Money`` stores the *exact* Decimal it is given; it does not
force-quantize on construction (intermediate calculations may carry sub-cent
precision). Apply the canonical 2-dp banker's rounding explicitly via
:meth:`Money.quantize` (and :func:`common.money.convert` quantizes at the FX
boundary).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from src.money.currency import Currency
from src.money.errors import CurrencyMismatchError, FloatNotAllowedError
from src.money.rounding import to_money

# Amount inputs accepted at construction. ``bool`` is an ``int`` subclass but is
# never a valid amount, so it is rejected explicitly below.
_AmountInput = Decimal | int


def _coerce_amount(value: object) -> Decimal:
    if isinstance(value, bool):
        raise FloatNotAllowedError("bool is not a valid Money amount")
    if isinstance(value, float):
        raise FloatNotAllowedError("float is not allowed for money amounts (IEEE-754 precision loss); use Decimal")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise FloatNotAllowedError(f"Money amount must be Decimal or int, got {type(value).__name__}")


@dataclass(frozen=True)
class Money:
    """An immutable amount in a single currency.

    >>> Money(Decimal("10.00"), "SGD") + Money(Decimal("5"), "SGD")
    Money(amount=Decimal('15.00'), currency=Currency(code='SGD'))
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _coerce_amount(self.amount))
        object.__setattr__(self, "currency", Currency.of(self.currency))

    # ── construction helpers ────────────────────────────────────────────
    @classmethod
    def zero(cls, currency: Currency | str) -> Money:
        return cls(Decimal("0"), currency)

    # ── rounding ────────────────────────────────────────────────────────
    def quantize(self, rounding: str = ROUND_HALF_EVEN) -> Money:
        """Return this amount rounded to the canonical 2-dp money quantum.

        Default rounding is the project-wide banker's rounding; an explicit
        ``rounding`` mode is accepted for the rare boundary that needs another.
        """
        if rounding == ROUND_HALF_EVEN:
            return Money(to_money(self.amount), self.currency)
        return Money(self.amount.quantize(Decimal("0.01"), rounding=rounding), self.currency)

    # ── same-currency arithmetic ────────────────────────────────────────
    def _require_same_currency(self, other: Money, op: str) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"cannot {op} Money and {type(other).__name__}")
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"cannot {op} across currencies: {self.currency.code} and {other.currency.code} — use convert()"
            )

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other, "add")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other, "subtract")
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __mul__(self, factor: _AmountInput) -> Money:
        """Scale by a dimensionless Decimal/int factor (not by another Money)."""
        return Money(self.amount * _coerce_amount(factor), self.currency)

    __rmul__ = __mul__

    # ── same-currency ordering ──────────────────────────────────────────
    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other, "compare")
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other, "compare")
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._require_same_currency(other, "compare")
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._require_same_currency(other, "compare")
        return self.amount >= other.amount

    def __str__(self) -> str:
        return f"{self.amount} {self.currency.code}"
