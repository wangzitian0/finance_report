from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.orm.ai_feedback import AiFeedback
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.identity import User
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def _seed_suggestion(
    db: AsyncSession,
    user_id: UUID,
    *,
    confidence: int,
    description: str,
    status_value: ClassificationStatus = ClassificationStatus.DRAFT,
    tags: dict | None = ...,
) -> TransactionClassification:
    atomic = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2024, 6, 1),
        amount=Decimal("12.34"),
        direction=TransactionDirection.OUT,
        description=description,
        currency="SGD",
        dedup_hash=f"ai-suggestion-{uuid4()}",
        source_documents=[],
    )
    db.add(atomic)
    await db.flush()
    rule = ClassificationRule(
        user_id=user_id,
        version_number=1,
        effective_date=date(2024, 1, 1),
        rule_name=f"rule-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["coffee"]},
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()
    cls = TransactionClassification(
        atomic_txn_id=atomic.id,
        rule_version_id=rule.id,
        confidence_score=confidence,
        status=status_value,
        tags={"category": "Food"} if tags is ... else tags,
    )
    db.add(cls)
    await db.flush()
    return cls


async def test_ac18_5_4_post_ai_feedback_persists_accept_and_edit_accept(client: AsyncClient, db: AsyncSession, test_user: User) -> None:
    draft = await _seed_suggestion(db, test_user.id, confidence=72, description="Coffee accept")
    draft_edit = await _seed_suggestion(db, test_user.id, confidence=72, description="Coffee edit")
    await db.commit()

    resp1 = await client.post("/statements/classification-feedback", json={"suggestion_id": str(draft.id), "action": "accept"})
    data1 = resp1.json()
    persisted = await db.get(AiFeedback, UUID(data1["id"]))
    assert (resp1.status_code, data1["suggestion_id"], data1["user_id"], data1["action"], data1["corrected_value"], persisted is not None, persisted.suggestion_id, persisted.user_id) == (
        status.HTTP_201_CREATED, str(draft.id), str(test_user.id), "accept", None, True, draft.id, test_user.id
    )

    corrected_value = {"category": "Dining", "confidence_note": "User corrected merchant category"}
    resp2 = await client.post("/statements/classification-feedback", json={"suggestion_id": str(draft_edit.id), "action": "edit_accept", "corrected_value": corrected_value})
    fb = (await db.execute(select(AiFeedback).where(AiFeedback.suggestion_id == draft_edit.id))).scalar_one()
    assert (resp2.status_code, resp2.json()["action"], resp2.json()["corrected_value"], fb.corrected_value) == (status.HTTP_201_CREATED, "edit_accept", corrected_value, corrected_value)


async def test_ac18_5_4_post_ai_feedback_missing_and_invalid_action(client: AsyncClient, db: AsyncSession) -> None:
    missing_id = uuid4()
    r404 = await client.post("/statements/classification-feedback", json={"suggestion_id": str(missing_id), "action": "accept"})
    stored = (await db.execute(select(AiFeedback).where(AiFeedback.suggestion_id == missing_id))).scalars().all()
    r422 = await client.post("/statements/classification-feedback", json={"suggestion_id": str(uuid4()), "action": "maybe"})
    assert (r404.status_code, stored, r422.status_code) == (status.HTTP_404_NOT_FOUND, [], status.HTTP_422_UNPROCESSABLE_ENTITY)


async def test_ac18_5_6_get_ai_suggestions_empty_review_band_and_fallback(client: AsyncClient, db: AsyncSession, test_user: User) -> None:
    empty_resp = await client.get("/statements/classification-suggestions")
    assert (empty_resp.status_code, empty_resp.json()) == (200, {"items": [], "total": 0})

    cls = await _seed_suggestion(db, test_user.id, confidence=72, description="Coffee shop")
    await _seed_suggestion(db, test_user.id, confidence=40, description="Below band")
    await _seed_suggestion(db, test_user.id, confidence=90, description="Above band")
    await _seed_suggestion(db, test_user.id, confidence=70, description="Already applied", status_value=ClassificationStatus.APPLIED)
    await _seed_suggestion(db, test_user.id, confidence=70, description="Fallback txn", tags=None)
    await db.commit()
    resp = await client.get("/statements/classification-suggestions")
    items = resp.json()["items"]
    by_desc = {it["transaction"]: it for it in items}
    assert (resp.status_code, len(items), by_desc["Coffee shop"]["suggestion_id"], by_desc["Coffee shop"]["ai_score"], by_desc["Fallback txn"]["suggested_category_or_match"]) == (
        200, 2, str(cls.id), 72, "AI classification"
    )


async def test_ac18_5_6_pagination_and_tenant_scope(client: AsyncClient, db: AsyncSession, test_user: User) -> None:
    other_user_id = (await UserFactory.create_async(db)).id
    await _seed_suggestion(db, other_user_id, confidence=70, description="Other user txn")
    await db.commit()
    scoped = await client.get("/statements/classification-suggestions")
    assert (scoped.status_code, scoped.json()["items"], scoped.json()["total"]) == (200, [], 0)

    for idx in range(4):
        await _seed_suggestion(db, test_user.id, confidence=70 + idx, description=f"Txn {idx}")
    await db.commit()
    limited = await client.get("/statements/classification-suggestions?limit=2")
    paged = await client.get("/statements/classification-suggestions?limit=10&offset=2")
    assert (limited.status_code, len(limited.json()["items"]), paged.status_code, len(paged.json()["items"])) == (200, 2, 200, 2)


@pytest.mark.parametrize("limit", [10000, 0])
async def test_AC_extraction_classification_suggestions_1_list_rejects_unbounded_limit(client: AsyncClient, limit: int) -> None:
    assert (await client.get("/statements/classification-suggestions", params={"limit": limit})).status_code == 422
