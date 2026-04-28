"""API tests for EPIC-018 AI feedback loop endpoints."""

from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AiFeedback, User

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
