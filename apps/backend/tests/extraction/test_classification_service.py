from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.composition import _get_or_create_default_counter_account
from src.extraction import RuleType, TransactionDirection
from src.extraction.extension.classification import ClassificationService
from src.extraction.extension.review_queue import get_or_create_account
from src.extraction.extension.transaction_classification import (
    ClassificationPolicy,
    TransactionCategory,
    _ensure_policy_rule,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import AccountType
from tests.extraction._statement_run_helpers import make_account
from tests.factories import AtomicTransactionFactory


async def _add_rule(
    db,
    user_id,
    *,
    name: str,
    rule_type: RuleType,
    config: dict,
    account_id,
    version: int = 1,
    effective: date = date(2024, 1, 1),
) -> ClassificationRule:
    rule = ClassificationRule(
        user_id=user_id,
        version_number=version,
        effective_date=effective,
        rule_name=name,
        rule_type=rule_type,
        rule_config=config,
        default_account_id=account_id,
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()
    return rule


async def _add_txn(db, user_id, description: str, dedup_hash: str, *, amount: str = "50.00", source_docs=None):
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2024, 1, 15),
        amount=Decimal(amount),
        direction=TransactionDirection.OUT,
        description=description,
        currency="SGD",
        dedup_hash=dedup_hash,
        source_documents=source_docs or [],
    )
    db.add(txn)
    await db.flush()
    return txn


@pytest.mark.parametrize(
    ("rule_type", "config", "descriptions", "matched_indices"),
    [
        (RuleType.KEYWORD_MATCH, {"keywords": ["fairprice", "shengsiong"]}, ["NTUC FAIRPRICE", "Unknown Merchant"], [0]),
        (RuleType.REGEX_MATCH, {"pattern": r"^GRAB\s+\w+"}, ["GRAB RIDE payment", "GOJEK RIDE payment"], [0]),
        (RuleType.REGEX_MATCH, {"pattern": ""}, ["Some Transaction"], []),
        (RuleType.REGEX_MATCH, {"pattern": "restaurant", "case_insensitive": True}, ["RESTAURANT XYZ", "the restaurant abc"], [0, 1]),
        (RuleType.REGEX_MATCH, {"pattern": "AMAZON", "case_insensitive": False}, ["AMAZON Purchase", "amazon purchase"], [0]),
        (RuleType.REGEX_MATCH, {}, ["Some Transaction"], []),
        (RuleType.KEYWORD_MATCH, {"keywords": []}, ["NTUC FAIRPRICE"], []),
        (RuleType.KEYWORD_MATCH, {"keywords": ["NONEXISTENT_KEYWORD_ZZZ"]}, ["Some Transaction UNKNOWN"], []),
    ],
)
async def test_apply_rules_matching_variants(db, test_user, rule_type, config, descriptions, matched_indices):
    account = await make_account(db, test_user.id, "Category", AccountType.EXPENSE, code="6000")
    rule = await _add_rule(db, test_user.id, name="Rule", rule_type=rule_type, config=config, account_id=account.id)
    txns = [await _add_txn(db, test_user.id, desc, f"h-{i}") for i, desc in enumerate(descriptions)]
    results = await ClassificationService().apply_rules(db, test_user.id, txns)
    assert [(r.atomic_txn_id, r.account_id, r.rule_version_id) for r in results] == [
        (txns[i].id, account.id, rule.id) for i in matched_indices
    ]


async def test_apply_rules_edge_cases_and_priority(db, test_user):
    service = ClassificationService()
    txn_none = await _add_txn(db, test_user.id, "No rules txn", "h-none")
    assert await service.apply_rules(db, test_user.id, [txn_none]) == []

    bad_acct = await make_account(db, test_user.id, "Invalid", AccountType.EXPENSE, code="6500")
    await _add_rule(db, test_user.id, name="Invalid", rule_type=RuleType.REGEX_MATCH, config={"pattern": "(unclosed[group"}, account_id=bad_acct.id)
    with patch("src.extraction.extension.classification.logger") as mock_logger:
        assert await service.apply_rules(db, test_user.id, [txn_none]) == []
        assert "Invalid regex pattern" in mock_logger.warning.call_args[0][0]

    kw_acct = await make_account(db, test_user.id, "Keyword", AccountType.EXPENSE, code="6812")
    rx_acct = await make_account(db, test_user.id, "Regex", AccountType.EXPENSE, code="6813")
    await _add_rule(db, test_user.id, name="KW", rule_type=RuleType.KEYWORD_MATCH, config={"keywords": ["food"]}, account_id=kw_acct.id)
    await _add_rule(db, test_user.id, name="RX", rule_type=RuleType.REGEX_MATCH, config={"pattern": "food"}, account_id=rx_acct.id)
    txn_prio = await _add_txn(db, test_user.id, "food delivery", "h-prio", source_docs=[{"category_confidence": "0.95"}])
    res_prio = await service.apply_rules(db, test_user.id, [txn_prio])
    assert len(res_prio) == 1 and res_prio[0].account_id == kw_acct.id

    old_acct = await make_account(db, test_user.id, "Old", AccountType.EXPENSE, code="6817")
    new_acct = await make_account(db, test_user.id, "New", AccountType.EXPENSE, code="6818")
    await _add_rule(db, test_user.id, name="Grocery", rule_type=RuleType.KEYWORD_MATCH, config={"keywords": ["grocery"]}, account_id=old_acct.id, version=1)
    new_rule = await _add_rule(db, test_user.id, name="Grocery", rule_type=RuleType.KEYWORD_MATCH, config={"keywords": ["grocery"]}, account_id=new_acct.id, version=2, effective=date(2024, 2, 1))
    txn_ver = await _add_txn(db, test_user.id, "Grocery store", "h-ver")
    res_ver = await service.apply_rules(db, test_user.id, [txn_ver])
    assert (len(res_ver), res_ver[0].rule_version_id, res_ver[0].account_id) == (1, new_rule.id, new_acct.id)

    first = await service.apply_rules(db, test_user.id, [txn_ver])
    second = await service.apply_rules(db, test_user.id, [txn_ver])
    stored = (await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == txn_ver.id, TransactionClassification.rule_version_id == new_rule.id))).scalars().all()
    assert (len(first), len(second), second[0].id, len(stored)) == (1, 1, first[0].id, 1)


async def test_AC18_1_3_ml_rule_matching_is_retired(db, test_user):
    service = ClassificationService()
    assert not hasattr(service, "_extract_ai_signals")
    db.add(ClassificationRule(user_id=test_user.id, version_number=1, effective_date=date(2024, 1, 1), rule_name="legacy-ml", rule_type=RuleType.ML_MODEL, rule_config={"source": "extraction_ai"}, created_by=test_user.id))
    await db.flush()
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="anything")
    assert await service.apply_rules(db, test_user.id, [txn]) == []


@pytest.mark.parametrize("kind", ["account", "policy_rule", "default_counter"])
async def test_session_caches_memoize_without_re_querying(db, test_user, kind):
    if kind == "account":
        first = await get_or_create_account(db, name="Test Category Account", account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id)
        assert (test_user.id, "Test Category Account", AccountType.EXPENSE, "SGD") in db.info.get("_default_account_cache", {})
        call = lambda: get_or_create_account(db, name="Test Category Account", account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id)
    elif kind == "policy_rule":
        policy = ClassificationPolicy(version=999, model_version="test-model-v1", catalog=(TransactionCategory.DINING, TransactionCategory.TRANSPORT), auto_apply_threshold=90, review_threshold=70, effective_from="2026-01-01")
        first = await _ensure_policy_rule(db, test_user.id, policy)
        assert (test_user.id, policy.version) in db.info.get("_policy_rule_cache", {})
        call = lambda: _ensure_policy_rule(db, test_user.id, policy)
    else:
        first = await _get_or_create_default_counter_account(db, test_user.id, AccountType.INCOME, "USD")
        assert (test_user.id, "General Income (USD)", AccountType.INCOME, "USD") in db.info.get("_default_account_cache", {})
        call = lambda: _get_or_create_default_counter_account(db, test_user.id, AccountType.INCOME, "USD")
    assert first is not None
    with patch.object(db, "execute", side_effect=RuntimeError("database query attempted")):
        assert await call() is first
