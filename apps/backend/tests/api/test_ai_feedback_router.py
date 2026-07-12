"""API tests for EPIC-018 AI feedback loop endpoints."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import AiFeedback, User
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.layer3 import ClassificationRule, ClassificationStatus, RuleType, TransactionClassification
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def test_ac18_5_4_post_ai_feedback_persists_accept_action(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.4: POST /ai/feedback stores accept feedback for the current user."""
    suggestion_id = uuid4()

    response = await client.post(
        "/ai/feedback",
        json={"suggestion_id": str(suggestion_id), "action": "accept"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["suggestion_id"] == str(suggestion_id)
    assert data["user_id"] == str(test_user.id)
    assert data["action"] == "accept"
    assert data["corrected_value"] is None

    persisted = await db.get(AiFeedback, UUID(data["id"]))
    assert persisted is not None
    assert persisted.suggestion_id == suggestion_id
    assert persisted.user_id == test_user.id


async def test_ac18_5_4_post_ai_feedback_persists_edit_then_accept_payload(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC18.5.4: edit_accept stores corrected_value for the feedback loop."""
    suggestion_id = uuid4()
    corrected_value = {"category": "Expense - Food & Dining", "confidence_note": "User corrected merchant category"}

    response = await client.post(
        "/ai/feedback",
        json={
            "suggestion_id": str(suggestion_id),
            "action": "edit_accept",
            "corrected_value": corrected_value,
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["action"] == "edit_accept"
    assert data["corrected_value"] == corrected_value

    result = await db.execute(select(AiFeedback).where(AiFeedback.suggestion_id == suggestion_id))
    feedback = result.scalar_one()
    assert feedback.corrected_value == corrected_value


async def test_ac18_5_4_post_ai_feedback_rejects_invalid_action(client: AsyncClient) -> None:
    """AC18.5.4: feedback action is constrained to accept/reject/edit_accept."""
    response = await client.post(
        "/ai/feedback",
        json={"suggestion_id": str(uuid4()), "action": "maybe"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def _seed_classification_suggestion(
    db: AsyncSession,
    user_id: UUID,
    *,
    confidence: int,
    description: str,
    status_value: ClassificationStatus = ClassificationStatus.DRAFT,
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

    classification = TransactionClassification(
        atomic_txn_id=atomic.id,
        rule_version_id=rule.id,
        confidence_score=confidence,
        status=status_value,
        tags={"category": "Food"},
    )
    db.add(classification)
    await db.flush()
    return classification


async def _seed_reconciliation_suggestion(
    db: AsyncSession,
    user_id: UUID,
    *,
    match_score: int,
    description: str,
    status_value: ReconciliationStatus = ReconciliationStatus.PENDING_REVIEW,
) -> ReconciliationMatch:
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2024, 6, 2),
        description=description,
        amount=Decimal("25.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=f"recon-suggestion-{uuid4()}",
        source_documents=[],
    )
    db.add(txn)
    await db.flush()

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        status=status_value,
        match_score=match_score,
        score_breakdown={"ai_reasoning": "fuzzy match on amount and date"},
    )
    db.add(match)
    await db.flush()
    return match


async def test_ac18_5_6_get_ai_suggestions_returns_empty_when_no_pending_items(
    client: AsyncClient,
) -> None:
    """AC18.5.6: GET /ai/suggestions returns empty list and zero total when nothing pending."""
    response = await client.get("/ai/suggestions")
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0}


async def test_ac18_5_6_get_ai_suggestions_returns_classification_in_review_band(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.6: classifications with score in [60, 85) and DRAFT status surface as suggestions."""
    classification = await _seed_classification_suggestion(db, test_user.id, confidence=72, description="Coffee shop")
    await _seed_classification_suggestion(db, test_user.id, confidence=40, description="Below band")
    await _seed_classification_suggestion(db, test_user.id, confidence=90, description="Above band")
    await _seed_classification_suggestion(
        db,
        test_user.id,
        confidence=70,
        description="Already applied",
        status_value=ClassificationStatus.APPLIED,
    )
    await db.commit()

    response = await client.get("/ai/suggestions")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["suggestion_id"] == str(classification.id)
    assert item["transaction"] == "Coffee shop"
    assert item["ai_score"] == 72


async def test_ai_suggestions_fallback_uses_string_when_tags_none_and_account_missing(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    # Seed a classification with tags=None and account_id=None to hit fallback branch
    atomic = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2024, 6, 1),
        amount=Decimal("5.00"),
        direction=TransactionDirection.OUT,
        description="Fallback txn",
        currency="SGD",
        dedup_hash=f"ai-suggestion-{uuid4()}",
        source_documents=[],
    )
    db.add(atomic)
    await db.flush()

    rule = ClassificationRule(
        user_id=test_user.id,
        version_number=1,
        effective_date=date(2024, 1, 1),
        rule_name=f"rule-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["x"]},
        created_by=test_user.id,
    )
    db.add(rule)
    await db.flush()

    classification = TransactionClassification(
        atomic_txn_id=atomic.id,
        rule_version_id=rule.id,
        confidence_score=70,
        status=ClassificationStatus.DRAFT,
        tags=None,
        account_id=None,
    )
    db.add(classification)
    await db.commit()

    resp = await client.get("/ai/suggestions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(
        it["transaction"] == "Fallback txn" and it["suggested_category_or_match"] == "AI classification" for it in items
    )


async def test_ac18_5_6_get_ai_suggestions_returns_reconciliation_match_in_review_band(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.6: reconciliation matches with score in [60, 85) and PENDING_REVIEW surface."""
    match = await _seed_reconciliation_suggestion(db, test_user.id, match_score=75, description="Grocery store")
    await _seed_reconciliation_suggestion(db, test_user.id, match_score=50, description="Low score")
    await _seed_reconciliation_suggestion(db, test_user.id, match_score=95, description="Auto-accept band")
    await db.commit()

    response = await client.get("/ai/suggestions")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["suggestion_id"] == str(match.id)
    assert item["transaction"] == "Grocery store"
    assert item["ai_score"] == 75
    assert item["suggested_category_or_match"] == "Reconciliation match"
    assert "fuzzy match" in item["ai_reasoning"]
    assert body["total"] >= 1


async def test_ac18_5_6_get_ai_suggestions_combines_classification_and_reconciliation(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.6: response merges classification and reconciliation suggestions."""
    await _seed_classification_suggestion(db, test_user.id, confidence=70, description="Latte")
    await _seed_reconciliation_suggestion(db, test_user.id, match_score=80, description="Supermarket")
    await db.commit()

    response = await client.get("/ai/suggestions")
    assert response.status_code == 200
    body = response.json()
    descriptions = {item["transaction"] for item in body["items"]}
    assert descriptions == {"Latte", "Supermarket"}


async def test_ac18_5_6_get_ai_suggestions_respects_limit_and_offset(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.6: limit caps classification results; offset paginates classifications."""
    for idx in range(3):
        await _seed_classification_suggestion(db, test_user.id, confidence=70 + idx, description=f"Txn {idx}")
    await _seed_reconciliation_suggestion(db, test_user.id, match_score=70, description="Bank match")
    await db.commit()

    limited = await client.get("/ai/suggestions?limit=2")
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 2

    paged = await client.get("/ai/suggestions?limit=10&offset=2")
    assert paged.status_code == 200
    paged_descs = [item["transaction"] for item in paged.json()["items"]]
    assert "Bank match" in paged_descs


async def test_ac18_5_6_get_ai_suggestions_scopes_to_current_user(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.5.6: suggestions belonging to other users are not surfaced."""
    other_user_id = (await UserFactory.create_async(db)).id
    await _seed_classification_suggestion(db, other_user_id, confidence=70, description="Other user txn")
    await _seed_reconciliation_suggestion(db, other_user_id, match_score=72, description="Other user bank")
    await db.commit()

    response = await client.get("/ai/suggestions")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
