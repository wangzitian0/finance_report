"""AC-extraction.normalization.1: Pure domain tests for extraction normalization and identity hashing.

Verifies versioned transaction hashing and account-suffix normalization
without database or I/O overhead.
"""

import hashlib

import pytest

from src.extraction.base.normalization_engine import (
    compute_transaction_identity_hash,
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


def test_sanitize_account_last4():
    """Extracts up to the last 4 alphanumeric characters or returns None."""
    assert sanitize_account_last4("123-456-7890") == "7890"
    assert sanitize_account_last4("ACC*9876") == "9876"
    assert sanitize_account_last4("12") == "12"
    assert sanitize_account_last4("---") is None
    assert sanitize_account_last4(None) is None
