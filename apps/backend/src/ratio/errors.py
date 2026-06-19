"""Typed errors for the ratio value type (mirrors the money error hierarchy).

A single narrow hierarchy so call-sites can catch ``RatioError`` for any
ratio-domain violation, or the specific subtype.
"""

from __future__ import annotations


class RatioError(Exception):
    """Base class for every ratio-domain error."""


class FloatNotAllowedError(RatioError, TypeError):
    """A ``float`` was supplied where a ``Decimal`` (or ``int``) is required.

    ``float`` is the standing numeric red line (IEEE-754 precision loss); the
    value type rejects it at construction rather than relying on review.
    """


class UndefinedRatioError(RatioError, ZeroDivisionError):
    """A ratio was requested from a zero whole (``part / 0`` is undefined)."""


class InvalidRatioPayloadError(RatioError, ValueError):
    """A serialized ratio payload is missing or malformed."""
