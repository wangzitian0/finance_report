"""API tests for user management endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.security import create_access_token

pytestmark = pytest.mark.asyncio


async def test_delete_current_user_removes_authenticated_user(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC8.13.109: isolated E2E users can be cleaned up after provider gates."""
    response = await client.delete(f"/users/{test_user.id}")

    assert response.status_code == 204
    assert await db.scalar(select(User.id).where(User.id == test_user.id)) is None

    followup = await client.get("/users")
    assert followup.status_code == 401


async def test_delete_user_does_not_allow_cross_user_deletion(
    public_client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC8.13.109: cleanup endpoint remains scoped to the authenticated user."""
    other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)

    token = create_access_token(data={"sub": str(test_user.id)})
    response = await public_client.delete(
        f"/users/{other_user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert await db.scalar(select(User.id).where(User.id == other_user.id)) == other_user.id
