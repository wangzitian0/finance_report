"""Boundary codecs for backend quantity values."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from src.quantity.errors import FloatNotAllowedError, InvalidQuantityPayloadError
from src.quantity.quantity import Quantity

QuantityWire = dict[str, str]
QuantityDbFields = dict[str, Decimal | str]


def _decimal_to_wire(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _decimal_from_wire(value: object, what: str = "quantity value") -> Decimal:
    if isinstance(value, bool):
        raise FloatNotAllowedError(f"bool is not a valid {what}")
    if isinstance(value, float):
        raise FloatNotAllowedError(f"float is not allowed for {what}; use a decimal string")
    if not isinstance(value, str):
        raise FloatNotAllowedError(f"{what} must be encoded as a decimal string, got {type(value).__name__}")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidQuantityPayloadError(f"{what} is not a valid decimal string") from exc
    if not parsed.is_finite():
        raise FloatNotAllowedError(f"{what} must be finite")
    return parsed


def _payload_mapping(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise InvalidQuantityPayloadError(f"Quantity payload must be an object, got {type(payload).__name__}")
    return payload


def _field(payload: Mapping[str, object], key: str) -> object:
    try:
        return payload[key]
    except KeyError as exc:
        raise InvalidQuantityPayloadError(f"Quantity payload missing {key!r}") from exc


def quantity_to_wire(quantity: Quantity) -> QuantityWire:
    if not isinstance(quantity, Quantity):
        raise TypeError(f"quantity_to_wire expects Quantity, got {type(quantity).__name__}")
    return {"value": _decimal_to_wire(quantity.value), "unit": quantity.unit.code}


def quantity_from_wire(payload: object) -> Quantity:
    fields = _payload_mapping(payload)
    return Quantity(
        _decimal_from_wire(_field(fields, "value")),
        _field(fields, "unit"),
    )


def quantity_to_db_fields(quantity: Quantity) -> QuantityDbFields:
    if not isinstance(quantity, Quantity):
        raise TypeError(f"quantity_to_db_fields expects Quantity, got {type(quantity).__name__}")
    return {"value": quantity.value, "unit": quantity.unit.code}


def quantity_from_db_fields(value: object, unit: object) -> Quantity:
    return Quantity(value, unit)  # type: ignore[arg-type]
