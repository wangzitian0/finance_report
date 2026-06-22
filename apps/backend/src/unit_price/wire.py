"""Boundary codecs for unit-price values (mirrors common/unit_price/wire.py)."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from src.decimal_scalar import WireCodec, decimal_to_wire as _decimal_to_wire
from src.unit_price.errors import FloatNotAllowedError, InvalidUnitPricePayloadError
from src.unit_price.unit_price import UnitPrice

UnitPriceWire = dict[str, str]
UnitPriceDbFields = dict[str, Decimal | str]

# The shared scalar codec bound to unit-price's typed errors (parse / mapping / field).
_CODEC = WireCodec(FloatNotAllowedError, InvalidUnitPricePayloadError)


def _decimal_from_wire(value: object, what: str = "unit-price rate") -> Decimal:
    return _CODEC.parse(value, what)


def _payload_mapping(payload: object) -> Mapping[str, object]:
    return _CODEC.mapping(payload, "UnitPrice")


def _field(payload: Mapping[str, object], key: str) -> object:
    return _CODEC.field(payload, key, "UnitPrice")


def unit_price_to_wire(unit_price: UnitPrice) -> UnitPriceWire:
    if not isinstance(unit_price, UnitPrice):
        raise TypeError(f"unit_price_to_wire expects UnitPrice, got {type(unit_price).__name__}")
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
        raise TypeError(f"unit_price_to_db_fields expects UnitPrice, got {type(unit_price).__name__}")
    return {
        "rate": unit_price.rate,
        "currency": unit_price.currency.code,
        "unit": unit_price.unit.code,
    }


def unit_price_from_db_fields(rate: object, currency: object, unit: object) -> UnitPrice:
    return UnitPrice(rate, currency, unit)  # type: ignore[arg-type]
