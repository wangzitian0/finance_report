"""Boundary codecs for unit-price values.

Wire payloads use decimal strings (never JSON numbers); DB adapters expose the
exact ``Decimal`` rate at the storage edge. Currency/unit cross the boundary as
their canonical string codes.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from common.unit_price.errors import FloatNotAllowedError, InvalidUnitPricePayloadError
from common.unit_price.unit_price import UnitPrice

UnitPriceWire = dict[str, str]
UnitPriceDbFields = dict[str, Decimal | str]


def _decimal_to_wire(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _decimal_from_wire(value: object, what: str = "unit-price rate") -> Decimal:
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
        raise InvalidUnitPricePayloadError(
            f"{what} is not a valid decimal string"
        ) from exc
    if not parsed.is_finite():
        raise FloatNotAllowedError(f"{what} must be finite")
    return parsed


def _payload_mapping(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise InvalidUnitPricePayloadError(
            f"UnitPrice payload must be an object, got {type(payload).__name__}"
        )
    return payload


def _field(payload: Mapping[str, object], key: str) -> object:
    try:
        return payload[key]
    except KeyError as exc:
        raise InvalidUnitPricePayloadError(
            f"UnitPrice payload missing {key!r}"
        ) from exc


def unit_price_to_wire(unit_price: UnitPrice) -> UnitPriceWire:
    if not isinstance(unit_price, UnitPrice):
        raise TypeError(
            f"unit_price_to_wire expects UnitPrice, got {type(unit_price).__name__}"
        )
    return {
        "rate": _decimal_to_wire(unit_price.rate),
        "currency": unit_price.currency.code,
        "unit": unit_price.unit.code,
    }


def unit_price_from_wire(payload: object) -> UnitPrice:
    fields = _payload_mapping(payload)
    return UnitPrice(
        _decimal_from_wire(_field(fields, "rate")),
        _field(fields, "currency"),  # type: ignore[arg-type]
        _field(fields, "unit"),  # type: ignore[arg-type]
    )


def unit_price_to_db_fields(unit_price: UnitPrice) -> UnitPriceDbFields:
    if not isinstance(unit_price, UnitPrice):
        raise TypeError(
            f"unit_price_to_db_fields expects UnitPrice, got {type(unit_price).__name__}"
        )
    return {
        "rate": unit_price.rate,
        "currency": unit_price.currency.code,
        "unit": unit_price.unit.code,
    }


def unit_price_from_db_fields(
    rate: object, currency: object, unit: object
) -> UnitPrice:
    return UnitPrice(rate, currency, unit)  # type: ignore[arg-type]
