"""Shared test-time base-value adapters.

These helpers are intentionally test/fixture scoped. They keep E2E and fixture
assertions ergonomic while routing semantic conversion through the same base
packages used by production code.
"""

from __future__ import annotations

from decimal import Decimal

from common.money import FloatNotAllowedError, Money


def money_amount(value: object, currency: str = "USD") -> Decimal:
    """Return a canonically quantized money amount for tests and fixtures."""
    if isinstance(value, bool) or isinstance(value, float):
        raise FloatNotAllowedError("test money_amount expects Decimal, int, or string")
    return Money(Decimal(str(value)), currency).quantize().amount
