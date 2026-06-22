"""Boundary codecs for quantity values."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from common.decimal_scalar import WireCodec
from common.decimal_scalar import decimal_to_wire as _decimal_to_wire
from common.quantity.errors import FloatNotAllowedError, InvalidQuantityPayloadError
from common.quantity.quantity import Quantity

QuantityWire = dict[str, str]
QuantityDbFields = dict[str, Decimal | str]

# The shared scalar codec bound to quantity's typed errors (parse / mapping / field).
_CODEC = WireCodec(FloatNotAllowedError, InvalidQuantityPayloadError)


def _decimal_from_wire(value: object, what: str = "quantity value") -> Decimal:
    return _CODEC.parse(value, what)


def _payload_mapping(payload: object) -> Mapping[str, object]:
    return _CODEC.mapping(payload, "Quantity")


def _field(payload: Mapping[str, object], key: str) -> object:
    return _CODEC.field(payload, key, "Quantity")


def quantity_to_wire(quantity: Quantity) -> QuantityWire:
    if not isinstance(quantity, Quantity):
        raise TypeError(
            f"quantity_to_wire expects Quantity, got {type(quantity).__name__}"
        )
    return {"value": _decimal_to_wire(quantity.value), "unit": quantity.unit.code}


def quantity_from_wire(payload: object) -> Quantity:
    fields = _payload_mapping(payload)
    return Quantity(
        _decimal_from_wire(_field(fields, "value")),
        _field(fields, "unit"),
    )


def quantity_to_db_fields(quantity: Quantity) -> QuantityDbFields:
    if not isinstance(quantity, Quantity):
        raise TypeError(
            f"quantity_to_db_fields expects Quantity, got {type(quantity).__name__}"
        )
    return {"value": quantity.value, "unit": quantity.unit.code}


def quantity_from_db_fields(value: object, unit: object) -> Quantity:
    return Quantity(value, unit)  # type: ignore[arg-type]
