"""Extra API tests to cover edge branches in ai suggestions."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.layer3 import ClassificationStatus, TransactionClassification
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus

pytestmark = pytest.mark.asyncio


async def _create_classification(
    db: AsyncSession, user_id, *, tags, account_id=None, confidence=70, status=ClassificationStatus.DRAFT
):
    atomic = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2024, 6, 1),
        amount=Decimal("1.23"),
        direction=TransactionDirection.OUT,
        description="Edge txn",
        currency="SGD",
        dedup_hash=f"edge-{uuid4()}",
        source_documents=[],
    )
    db.add(atomic)
    await db.flush()

    # create a minimal classification rule to satisfy not-null constraint
    from src.models.layer3 import ClassificationRule, RuleType

    rule = ClassificationRule(
        user_id=user_id,
        version_number=1,
        effective_date=date(2024, 1, 1),
        rule_name=f"r-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["edge"]},
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()

    classification = TransactionClassification(
        atomic_txn_id=atomic.id,
        rule_version_id=rule.id,
        confidence_score=confidence,
        status=status,
        tags=tags,
        account_id=account_id,
    )
    db.add(classification)
    await db.flush()
    return classification


async def _create_reconciliation(db: AsyncSession, user_id, *, match_score=70, score_breakdown=None):
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2024, 6, 2),
        description="Edge bank txn",
        amount=Decimal("5.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=f"edge-recon-{uuid4()}",
        source_documents=[],
    )
    db.add(txn)
    await db.flush()

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        status=ReconciliationStatus.PENDING_REVIEW,
        match_score=match_score,
        score_breakdown=score_breakdown or {},
    )
    db.add(match)
    await db.flush()
    return match


async def test_classification_tags_not_dict_uses_account_id(client: AsyncClient, db: AsyncSession, test_user: User):
    """If tags is not a dict, suggested_category_or_match falls back to account_id."""
    # create a real account and use its id
    from src.models.account import Account, AccountType

    acct = Account(id=uuid4(), user_id=test_user.id, name="Test acct", type=AccountType.ASSET, currency="SGD")
    db.add(acct)
    await db.flush()
    cls = await _create_classification(db, test_user.id, tags="not-a-dict", account_id=acct.id)
    await db.commit()

    resp = await client.get("/ai/suggestions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    # find our suggestion
    found = [i for i in items if i["suggestion_id"] == str(cls.id)]
    assert found, items
    assert found[0]["suggested_category_or_match"] == str(acct.id)


# Note: confidence_score fallback to 60 is defensive in code path but
# the query filters classifications with confidence_score >= 60, so
# creating a falsy confidence value will not surface the suggestion.
# We avoid testing that unreachable branch here.


async def test_reconciliation_ai_reasoning_default_when_missing(client: AsyncClient, db: AsyncSession, test_user: User):
    """If score_breakdown lacks ai_reasoning, the endpoint should use the default message."""
    match = await _create_reconciliation(db, test_user.id, match_score=75, score_breakdown={})
    await db.commit()

    resp = await client.get("/ai/suggestions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    found = [i for i in items if i["suggestion_id"] == str(match.id)]
    assert found
    assert "Pending AI reconciliation match" in found[0]["ai_reasoning"]
