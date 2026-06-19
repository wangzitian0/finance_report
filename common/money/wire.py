"""Boundary codecs for money values."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from common.money.errors import FloatNotAllowedError, InvalidMoneyPayloadError
from common.money.exchange_rate import ExchangeRate
from common.money.money import Money

MoneyWire = dict[str, str]
ExchangeRateWire = dict[str, str]
MoneyDbFields = dict[str, Decimal | str]
ExchangeRateDbFields = dict[str, Decimal | str]


def _decimal_to_wire(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _decimal_from_wire(value: object, what: str) -> Decimal:
    if isinstance(value, bool):
        raise FloatNotAllowedError(f"bool is not a valid {what}")
    if isinstance(value, float):
        raise FloatNotAllowedError(
            f"float is not allowed for {what}; use a decimal string"
        )
    if not isinstance(value, str):
        raise FloatNotAllowedError(
            f"{what} must be encoded as a decimal string, got {type(value).__name__}"
        )
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidMoneyPayloadError(f"{what} is not a valid decimal string") from exc
    if not parsed.is_finite():
        raise FloatNotAllowedError(f"{what} must be finite")
    return parsed


def _payload_mapping(payload: object, what: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise InvalidMoneyPayloadError(
            f"{what} payload must be an object, got {type(payload).__name__}"
        )
    return payload


def _field(payload: Mapping[str, object], key: str, what: str) -> object:
    try:
        return payload[key]
    except KeyError as exc:
        raise InvalidMoneyPayloadError(f"{what} payload missing {key!r}") from exc


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
        raise TypeError(
            f"exchange_rate_to_wire expects ExchangeRate, got {type(rate).__name__}"
        )
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
        raise TypeError(
            f"exchange_rate_to_db_fields expects ExchangeRate, got {type(rate).__name__}"
        )
    return {"base": rate.base.code, "quote": rate.quote.code, "rate": rate.rate}


def exchange_rate_from_db_fields(
    base: object, quote: object, rate: object
) -> ExchangeRate:
    return ExchangeRate(base, quote, rate)  # type: ignore[arg-type]
