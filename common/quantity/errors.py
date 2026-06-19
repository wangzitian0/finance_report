"""Typed errors for the quantity value type."""

from __future__ import annotations


class QuantityError(Exception):
    """Base class for every quantity-domain error."""


class FloatNotAllowedError(QuantityError, TypeError):
    """A float/bool was supplied where an exact Decimal quantity is required."""


class InvalidUnitError(QuantityError, ValueError):
    """A quantity unit is empty or ambiguous."""


class UnitMismatchError(QuantityError, ValueError):
    """An operation combined quantities with different units."""


class InvalidQuantityPayloadError(QuantityError, ValueError):
    """A serialized quantity payload is missing or malformed."""
