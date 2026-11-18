"""Fail-closed base-currency boundary validation for domain services."""

from __future__ import annotations


def require_base_currency(base_currency: str | None) -> str:
    """Require an explicit, non-empty ISO-4217 currency code from the boundary."""
    normalized = base_currency.strip().upper() if isinstance(base_currency, str) else ""
    if not normalized:
        raise ValueError("base_currency is required")
    if len(normalized) != 3 or not (normalized.isascii() and normalized.isalpha()):
        raise ValueError(f"base_currency must be a 3-letter ISO-4217 code: {base_currency!r}")
    return normalized
