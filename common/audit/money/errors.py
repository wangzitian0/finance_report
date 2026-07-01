"""Typed errors for the money value types.

A single, narrow error hierarchy so call-sites can catch ``MoneyError`` for any
money-domain violation, or the specific subtype. The subtypes also inherit from
the stdlib exception that best matches their nature (``TypeError`` for a wrong
*type* such as ``float``; ``ValueError`` for a wrong *value* such as a non-ISO
currency or a cross-currency operation), so existing ``except (TypeError,
ValueError)`` handlers keep working.
"""

from __future__ import annotations


class MoneyError(Exception):
    """Base class for every money-domain error."""


class FloatNotAllowedError(MoneyError, TypeError):
    """A ``float`` was supplied where a ``Decimal`` (or ``int``) is required.

    ``float`` is the standing monetary red line (IEEE-754 precision loss); the
    value types reject it at construction rather than relying on review.
    """


class InvalidCurrencyError(MoneyError, ValueError):
    """A currency code is not a recognised ISO-4217 alphabetic code."""


class CurrencyMismatchError(MoneyError, ValueError):
    """An operation combined two different currencies without conversion.

    Same-currency ``+``/``-``/comparison is allowed; anything cross-currency must
    route through :func:`common.audit.money.convert`.
    """


class InvalidExchangeRateError(MoneyError, ValueError):
    """An exchange rate is zero, negative, non-finite, or otherwise invalid."""


class InvalidMoneyPayloadError(MoneyError, ValueError):
    """A serialized money or exchange-rate payload is missing or malformed."""
