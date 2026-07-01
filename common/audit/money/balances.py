"""Per-currency balance container — a multi-currency statement cannot collapse.

The bug behind #1139 / #1123 was a statement whose balance was a *scalar*
``(opening, closing, currency)``: a genuinely multi-currency NAV silently
collapsed onto one currency. :class:`CurrencyBalances` makes that
unrepresentable — it holds one :class:`CurrencyBalance` per currency and exposes
**no** single scalar ``amount``/``currency`` that would stand in for "the
balance" across currencies. Summing across currencies is intentionally not
offered (it requires :func:`common.audit.money.convert` and a chosen base currency).

It round-trips the existing ``StatementSummary.currency_balances`` JSONB shape
``[{"currency", "opening", "closing"}]`` so adoption (PR2, #1171) is a typed
accessor over the column rather than a migration. Amounts are serialised as
strings (never JSON floats) per the decimal red line.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from common.audit.money.currency import Currency
from common.audit.money.errors import (
    FloatNotAllowedError,
    InvalidCurrencyError,
    MoneyError,
)
from common.audit.money.money import Money


@dataclass(frozen=True)
class CurrencyBalance:
    """Opening and closing balance for a single currency."""

    currency: Currency
    opening: Money
    closing: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", Currency.of(self.currency))
        for field_name in ("opening", "closing"):
            value = getattr(self, field_name)
            if not isinstance(value, Money):
                raise MoneyError(
                    f"{field_name} must be a Money, got {type(value).__name__}"
                )
            if value.currency != self.currency:
                raise MoneyError(
                    f"{field_name} currency {value.currency.code} != bucket "
                    f"currency {self.currency.code}"
                )


def _parse_amount(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise FloatNotAllowedError(f"{field_name} must not be a float/bool")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise FloatNotAllowedError(
        f"{field_name} must be Decimal/int/str, got {type(value).__name__}"
    )


@dataclass(frozen=True)
class CurrencyBalances:
    """An immutable set of per-currency opening/closing balances.

    There is deliberately no scalar accessor that would let a multi-currency
    balance masquerade as one currency. Access is always per currency.
    """

    balances: tuple[CurrencyBalance, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for bal in self.balances:
            if bal.currency.code in seen:
                raise MoneyError(f"duplicate currency in balances: {bal.currency.code}")
            seen.add(bal.currency.code)

    # ── access (per currency only) ──────────────────────────────────────
    def currencies(self) -> tuple[str, ...]:
        return tuple(bal.currency.code for bal in self.balances)

    def get(self, currency: Currency | str) -> CurrencyBalance | None:
        code = Currency.of(currency).code
        for bal in self.balances:
            if bal.currency.code == code:
                return bal
        return None

    def is_multi_currency(self) -> bool:
        return len(self.balances) > 1

    def __iter__(self):
        return iter(self.balances)

    def __len__(self) -> int:
        return len(self.balances)

    # ── JSONB round-trip (StatementSummary.currency_balances) ───────────
    @classmethod
    def from_jsonb(cls, rows: list[dict] | None) -> CurrencyBalances:
        """Build from the ``[{currency, opening, closing}]`` JSONB shape."""
        if not rows:
            return cls(())
        out: list[CurrencyBalance] = []
        for row in rows:
            code = row.get("currency")
            if code is None:
                raise InvalidCurrencyError("currency_balances row missing 'currency'")
            currency = Currency.of(code)
            opening = Money(_parse_amount(row.get("opening"), "opening"), currency)
            closing = Money(_parse_amount(row.get("closing"), "closing"), currency)
            out.append(CurrencyBalance(currency, opening, closing))
        return cls(tuple(out))

    def to_jsonb(self) -> list[dict]:
        """Serialise to the JSONB shape, amounts as strings (never floats)."""
        return [
            {
                "currency": bal.currency.code,
                "opening": str(bal.opening.amount),
                "closing": str(bal.closing.amount),
            }
            for bal in self.balances
        ]
