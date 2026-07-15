"""Typed FX conversion rate for the money package."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.audit.decimal_scalar import coerce_decimal
from src.audit.money.currency import Currency
from src.audit.money.errors import FloatNotAllowedError, InvalidExchangeRateError


def _coerce_rate(value: object) -> Decimal:
    """Coerce via the shared codec (AC-audit.36.2); positivity stays FX-specific."""
    rate = coerce_decimal(value, "FX rate", float_error=FloatNotAllowedError)
    if not rate.is_finite() or rate <= 0:
        raise InvalidExchangeRateError("FX rate must be finite and positive")
    return rate


@dataclass(frozen=True)
class ExchangeRate:
    """A directed FX rate: ``amount_quote = amount_base * rate``."""

    base: Currency
    quote: Currency
    rate: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", Currency.of(self.base))
        object.__setattr__(self, "quote", Currency.of(self.quote))
        object.__setattr__(self, "rate", _coerce_rate(self.rate))

    def inverse(self) -> ExchangeRate:
        return ExchangeRate(self.quote, self.base, Decimal("1") / self.rate)

    def __str__(self) -> str:
        return f"{self.base.code}/{self.quote.code} {self.rate}"
