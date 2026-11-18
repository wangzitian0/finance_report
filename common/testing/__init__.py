"""Shared test-time helpers."""

from __future__ import annotations

from decimal import Decimal

from common.audit.money import FloatNotAllowedError, Money

__all__ = ["money_amount"]


def money_amount(value: object, currency: str = "USD") -> Decimal:
    """Return a quantized money amount for tests and fixtures."""
    if isinstance(value, (bool, float)):
        raise FloatNotAllowedError("test money_amount expects Decimal, int, or string")
    return Money(Decimal(str(value)), currency).quantize().amount
