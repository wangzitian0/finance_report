"""AC-identity.1.3: Authenticated user management endpoint tests.

The public registration surface is /auth/register. The legacy /users router is
kept only for authenticated current-user operations and must not expose or
mutate other users.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.identity.extension.api.users import get_user, update_user
from src.schemas.user import UserUpdate

pytestmark = pytest.mark.asyncio


async def test_AC1_8_1_users_endpoints_require_auth(public_client: AsyncClient, test_user: User) -> None:
    """AC-identity.1.3: Legacy /users endpoints reject unauthenticated callers."""
    other_id = uuid4()

    responses = [
        await public_client.post("/users", json={"email": "new@example.com", "password": "securepassword123"}),
        await public_client.get("/users"),
        await public_client.get(f"/users/{test_user.id}"),
        await public_client.put(f"/users/{other_id}", json={"email": "updated@example.com"}),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]


async def test_AC1_8_1_create_user_route_no_longer_registers_users(client: AsyncClient) -> None:
    """AC-identity.1.3: User registration is constrained to /auth/register."""
    response = await client.post(
        "/users",
        json={"email": "legacy-create@example.com", "password": "securepassword123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Use /auth/register to create users"


async def test_AC1_8_1_list_users_returns_only_current_user(client: AsyncClient, test_user: User) -> None:
    """AC-identity.1.3: Listing users does not disclose other user records."""
    response = await client.get("/users")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [str(test_user.id)]


async def test_AC1_8_1_get_user_by_id_allows_current_user(client: AsyncClient, test_user: User) -> None:
    """AC-identity.1.3: Current user can read their own profile through the legacy route."""
    response = await client.get(f"/users/{test_user.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(test_user.id)
    assert data["email"] == test_user.email


async def test_AC1_8_1_get_user_by_id_hides_other_users(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC-identity.1.3: User lookups do not disclose another user's profile."""
    other = User(email="other-user@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()
    await db.refresh(other)

    response = await client.get(f"/users/{other.id}")

    assert response.status_code == 404


async def test_AC1_8_1_get_user_by_id_returns_not_found_when_current_user_record_is_missing(
    db: AsyncSession,
) -> None:
    """AC-identity.1.3: A valid token cannot disclose a deleted current-user row."""
    missing_user_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await get_user(user_id=missing_user_id, db=db, current_user_id=missing_user_id)

    assert exc_info.value.status_code == 404


async def test_AC1_8_1_update_user_email_allows_current_user(client: AsyncClient, test_user: User) -> None:
    """AC-identity.1.3: Current user can update their own email."""
    response = await client.put(f"/users/{test_user.id}", json={"email": "updated-current@example.com"})

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(test_user.id)
    assert data["email"] == "updated-current@example.com"


async def test_AC1_8_1_update_user_email_hides_other_users(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC-identity.1.3: Current user cannot mutate another user's email."""
    other = User(email="victim@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()
    await db.refresh(other)

    response = await client.put(f"/users/{other.id}", json={"email": "taken-over@example.com"})
    await db.refresh(other)

    assert response.status_code == 404
    assert other.email == "victim@example.com"


async def test_AC1_8_1_update_user_returns_not_found_when_current_user_record_is_missing(
    db: AsyncSession,
) -> None:
    """AC-identity.1.3: A valid token cannot recreate a deleted current-user row via update."""
    missing_user_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await update_user(
            user_id=missing_user_id,
            user_data=UserUpdate(email="deleted@example.com"),
            db=db,
            current_user_id=missing_user_id,
        )

    assert exc_info.value.status_code == 404


async def test_AC1_8_1_update_user_duplicate_email_rejected(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC-identity.1.3: Current-user update still enforces email uniqueness."""
    other = User(email="existing@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()

    response = await client.put(f"/users/{test_user.id}", json={"email": "existing@example.com"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid update data"
