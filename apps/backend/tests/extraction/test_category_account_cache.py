"""Unit tests for category account and policy rule session caching (EPIC-018 AC18.15)."""

from unittest.mock import patch

from src.composition import _get_or_create_default_counter_account
from src.extraction.extension.review_queue import get_or_create_account
from src.extraction.extension.transaction_classification import (
    ClassificationPolicy,
    TransactionCategory,
    _ensure_policy_rule,
)
from src.ledger import AccountType


async def test_get_or_create_account_memoizes_in_session_cache(db, test_user):
    """AC-extraction.1815.2: AC18.15.2: default accounts are cached in session info."""
    user_id = test_user.id
    name = "Test Category Account"
    account_type = AccountType.EXPENSE
    currency = "SGD"

    # First call creates the account and populates cache.
    first = await get_or_create_account(
        db,
        name=name,
        account_type=account_type,
        currency=currency,
        user_id=user_id,
    )
    assert first is not None
    assert (user_id, name, account_type, currency) in db.info.get("_default_account_cache", {})

    # Second call returns the cached object without database execution.
    with patch.object(db, "execute", side_effect=RuntimeError("database query attempted")):
        second = await get_or_create_account(
            db,
            name=name,
            account_type=account_type,
            currency=currency,
            user_id=user_id,
        )
    assert second is first


async def test_ensure_policy_rule_memoizes_in_session_cache(db, test_user):
    """AC-extraction.1815.1: AC18.15.1: policy rules are cached in session info."""
    user_id = test_user.id
    policy = ClassificationPolicy(
        version=999,
        model_version="test-model-v1",
        catalog=(TransactionCategory.DINING, TransactionCategory.TRANSPORT),
        auto_apply_threshold=90,
        review_threshold=70,
        effective_from="2026-01-01",
    )

    first = await _ensure_policy_rule(db, user_id, policy)
    assert first is not None
    assert (user_id, policy.version) in db.info.get("_policy_rule_cache", {})

    with patch.object(db, "execute", side_effect=RuntimeError("database query attempted")):
        second = await _ensure_policy_rule(db, user_id, policy)
    assert second is first


async def test_get_or_create_default_counter_account_memoizes_in_session_cache(db, test_user):
    """AC-extraction.1815.2: AC18.15.2: counter accounts are cached in session info."""
    user_id = test_user.id
    account_type = AccountType.INCOME
    currency = "USD"
    expected_name = "General Income (USD)"

    first = await _get_or_create_default_counter_account(db, user_id, account_type, currency)
    assert first is not None
    assert (user_id, expected_name, account_type, currency) in db.info.get("_default_account_cache", {})

    with patch.object(db, "execute", side_effect=RuntimeError("database query attempted")):
        second = await _get_or_create_default_counter_account(db, user_id, account_type, currency)
    assert second is first
