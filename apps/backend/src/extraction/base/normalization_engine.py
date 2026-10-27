"""AC-extraction.normalization.1: Pure domain calculation core for extraction normalization & identity hashing.

Zero-DB, zero-mock, pure Python account-suffix normalization and versioned SHA-256 hashing.
"""

from __future__ import annotations

import re

from src.audit import text_digest


def compute_transaction_identity_hash(legacy_hash: str, currency: str, custody_scope: str) -> str:
    """Version salt prevents v1/v2 ambiguity without changing historical hashes."""
    normalized_currency = currency.strip().upper()
    return text_digest(f"v2|{normalized_currency}|{custody_scope}|{legacy_hash}")


def sanitize_account_last4(value: str | None) -> str | None:
    """Sanitize account_last4 to up to the last 4 alphanumeric characters.

    Strips non-alphanumeric characters and returns the trailing alphanumeric characters
    (maximum 4). Returns None if empty or containing no alphanumeric characters.
    Prevents StringDataRightTruncationError on VARCHAR(4) database columns.
    """
    if not value:
        return None
    alphanumeric_only = re.sub(r"[^a-zA-Z0-9]", "", value)
    return alphanumeric_only[-4:] if alphanumeric_only else None
