"""Boundary codecs for backend money values."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from src.audit.money.errors import FloatNotAllowedError, InvalidMoneyPayloadError
from src.audit.money.exchange_rate import ExchangeRate
from src.audit.money.money import Money
from src.decimal_scalar import WireCodec, decimal_to_wire as _decimal_to_wire

MoneyWire = dict[str, str]
ExchangeRateWire = dict[str, str]
MoneyDbFields = dict[str, Decimal | str]
ExchangeRateDbFields = dict[str, Decimal | str]

# The shared scalar codec bound to money's typed errors (parse / mapping / field).
_CODEC = WireCodec(FloatNotAllowedError, InvalidMoneyPayloadError)


def _decimal_from_wire(value: object, what: str) -> Decimal:
    return _CODEC.parse(value, what)


def _payload_mapping(payload: object, what: str) -> Mapping[str, object]:
    return _CODEC.mapping(payload, what)


def _field(payload: Mapping[str, object], key: str, what: str) -> object:
    return _CODEC.field(payload, key, what)


def money_to_wire(money: Money) -> MoneyWire:
    if not isinstance(money, Money):
        raise TypeError(f"money_to_wire expects Money, got {type(money).__name__}")
    return {"amount": _decimal_to_wire(money.amount), "currency": money.currency.code}


def money_from_wire(payload: object) -> Money:
    fields = _payload_mapping(payload, "Money")
    return Money(
        _decimal_from_wire(_field(fields, "amount", "Money"), "Money amount"),
        _field(fields, "currency", "Money"),
    )


def money_to_db_fields(money: Money) -> MoneyDbFields:
    if not isinstance(money, Money):
        raise TypeError(f"money_to_db_fields expects Money, got {type(money).__name__}")
    return {"amount": money.amount, "currency": money.currency.code}


def money_from_db_fields(amount: object, currency: object) -> Money:
    return Money(amount, currency)  # type: ignore[arg-type]


def exchange_rate_to_wire(rate: ExchangeRate) -> ExchangeRateWire:
    if not isinstance(rate, ExchangeRate):
        raise TypeError(f"exchange_rate_to_wire expects ExchangeRate, got {type(rate).__name__}")
    return {
        "base": rate.base.code,
        "quote": rate.quote.code,
        "rate": _decimal_to_wire(rate.rate),
    }


def exchange_rate_from_wire(payload: object) -> ExchangeRate:
    fields = _payload_mapping(payload, "ExchangeRate")
    return ExchangeRate(
        _field(fields, "base", "ExchangeRate"),
        _field(fields, "quote", "ExchangeRate"),
        _decimal_from_wire(_field(fields, "rate", "ExchangeRate"), "FX rate"),
    )


def exchange_rate_to_db_fields(rate: ExchangeRate) -> ExchangeRateDbFields:
    if not isinstance(rate, ExchangeRate):
        raise TypeError(f"exchange_rate_to_db_fields expects ExchangeRate, got {type(rate).__name__}")
    return {"base": rate.base.code, "quote": rate.quote.code, "rate": rate.rate}


def exchange_rate_from_db_fields(base: object, quote: object, rate: object) -> ExchangeRate:
    return ExchangeRate(base, quote, rate)  # type: ignore[arg-type]
