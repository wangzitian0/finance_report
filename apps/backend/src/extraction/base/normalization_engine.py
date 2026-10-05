"""AC-extraction.normalization.1: Pure domain calculation core for extraction normalization & identity hashing.

Zero-DB, zero-mock, pure Python text normalization and versioned SHA-256 hashing.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

_SUFFIXES = (
    "PTE LTD",
    "PTE. LTD.",
    "LTD",
    "LTD.",
    "LIMITED",
    "INC",
    "INC.",
    "LLC",
    "CORP",
    "CORP.",
    "CORPORATION",
    "SDN BHD",
    "BHD",
    "SINGAPORE",
    "SG",
)

_SUFFIX_REGEX = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _SUFFIXES) + r")\b",
    re.IGNORECASE,
)


def compute_transaction_identity_hash(legacy_hash: str, currency: str, custody_scope: str) -> str:
    """Version salt prevents v1/v2 ambiguity without changing historical hashes."""
    normalized_currency = currency.strip().upper()
    raw = f"v2|{normalized_currency}|{custody_scope}|{legacy_hash}".encode()
    return hashlib.sha256(raw).hexdigest()


def normalize_merchant_token(raw_name: str) -> str:
    """Strip legal corporate suffixes, noise characters, and trailing tokens to extract clean merchant core."""
    if not raw_name:
        return ""

    text = raw_name.strip()
    # Replace noise punctuation and delimiters with space
    text = re.sub(r"[*#_.,/\\-]+", " ", text)
    # Remove known corporate suffixes
    text = _SUFFIX_REGEX.sub(" ", text)
    # Strip trailing numeric transaction/trace identifiers (e.g. 12345)
    text = re.sub(r"\s+\d+\s*$", "", text)
    # Collapse multiple whitespaces
    text = re.sub(r"\s+", " ", text).strip().upper()

    return text


def clean_statement_description(description: str) -> str:
    """Normalize statement transaction descriptions by stripping extraneous punctuation and excess whitespace."""
    if not description:
        return ""
    cleaned = re.sub(r"[*#_]+", " ", description)
    return re.sub(r"\s+", " ", cleaned).strip()


def sanitize_account_last4(value: str | None) -> str | None:
    """Extract exactly the last 4 alphanumeric characters from an account identifier string."""
    if not value:
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", value)
    return cleaned[-4:] if len(cleaned) >= 4 else None


def match_category_pattern(description: str, patterns: Sequence[str]) -> bool:
    """Check if description matches any of the given keyword patterns case-insensitively."""
    if not description or not patterns:
        return False
    desc_lower = description.lower()
    for pattern in patterns:
        if pattern.lower() in desc_lower:
            return True
    return False
