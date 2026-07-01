"""Typed errors for the unit-price value type (mirrors common/audit/unit_price/errors.py)."""

from __future__ import annotations


class UnitPriceError(Exception):
    """Base class for every unit-price-domain error."""


class FloatNotAllowedError(UnitPriceError, TypeError):
    """A ``float``/``bool`` was supplied where an exact ``Decimal`` is required."""


class CurrencyMismatchError(UnitPriceError, ValueError):
    """An operation combined unit prices in different currencies."""


class UnitMismatchError(UnitPriceError, ValueError):
    """A unit price was applied to a quantity in a different unit."""


class UndefinedUnitPriceError(UnitPriceError, ZeroDivisionError):
    """A unit price was derived from a zero quantity (``total / 0`` is undefined)."""


class InvalidUnitPricePayloadError(UnitPriceError, ValueError):
    """A serialized unit-price payload is missing or malformed."""
