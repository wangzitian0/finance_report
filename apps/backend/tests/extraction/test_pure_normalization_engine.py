"""AC-extraction.normalization.1: Pure domain tests for extraction normalization and identity hashing.

Verifies deterministic merchant token normalization, versioned transaction hashing,
and pattern matching rules without database or I/O overhead.
"""

import hashlib

import pytest

from src.extraction.base.normalization_engine import (
    clean_statement_description,
    compute_transaction_identity_hash,
    match_category_pattern,
    normalize_merchant_token,
    sanitize_account_last4,
)

pytestmark = pytest.mark.no_db


def test_compute_transaction_identity_hash_stability():
    """Hash generation follows strict v2 salt specification: v2|CURRENCY|custody_scope|legacy_hash."""
    legacy_hash = "abc123def456"
    currency = "SGD"
    custody_scope = "account:1111-2222"

    expected_raw = f"v2|{currency}|{custody_scope}|{legacy_hash}".encode()
    expected_digest = hashlib.sha256(expected_raw).hexdigest()

    result = compute_transaction_identity_hash(
        legacy_hash=legacy_hash,
        currency="sgd",  # tests lowercase normalization
        custody_scope=custody_scope,
    )
    assert result == expected_digest


def test_compute_transaction_identity_hash_falsification_on_scope_mutation():
    """Mutating custody scope or currency changes the transaction identity hash."""
    h1 = compute_transaction_identity_hash("hash1", "SGD", "account:1")
    h2 = compute_transaction_identity_hash("hash1", "USD", "account:1")
    h3 = compute_transaction_identity_hash("hash1", "SGD", "account:2")

    assert h1 != h2
    assert h1 != h3
    assert h2 != h3


def test_normalize_merchant_token():
    """Strips company suffixes, noise, card transaction codes, and preserves merchant core."""
    assert normalize_merchant_token("AMAZON SG PTE LTD") == "AMAZON"
    assert normalize_merchant_token("GRAB *TRANSPORT SINGAPORE") == "GRAB TRANSPORT"
    assert normalize_merchant_token("FAIRPRICE XTRA INC.") == "FAIRPRICE XTRA"
    assert normalize_merchant_token("NETFLIX.COM PAYMENT 12345") == "NETFLIX COM PAYMENT"
    assert normalize_merchant_token("STARBUCKS COFFEE CORP") == "STARBUCKS COFFEE"


def test_clean_statement_description():
    """Cleans multiple spaces and special characters for description matching."""
    raw = "  PAYMENT   TO   VENDOR   #99812   "
    assert clean_statement_description(raw) == "PAYMENT TO VENDOR 99812"


def test_sanitize_account_last4():
    """Extracts exactly the last 4 alphanumeric digits or returns None."""
    assert sanitize_account_last4("123-456-7890") == "7890"
    assert sanitize_account_last4("ACC*9876") == "9876"
    assert sanitize_account_last4("12") is None
    assert sanitize_account_last4(None) is None


def test_match_category_pattern():
    """Deterministic keyword and pattern matching for classification rules."""
    patterns = ["grab", "uber", "gojek", "comfortdelgro"]
    assert match_category_pattern("GRAB *RIDE 2025-01-10", patterns) is True
    assert match_category_pattern("ComfortDelGro Taxi Booking", patterns) is True
    assert match_category_pattern("STARBUCKS COFFEE", patterns) is False
