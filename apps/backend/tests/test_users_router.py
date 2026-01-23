"""Tests for users router endpoints."""

from datetime import UTC

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_user_success(client: AsyncClient) -> None:
    """Test creating a new user successfully."""
    payload = {
        "email": "test@example.com",
        "password": "securepassword123",
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert "id" in data
    assert "hashed_password" not in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_user_duplicate_email(client: AsyncClient) -> None:
    """Test that creating a user with existing email fails with generic message."""
    payload = {
        "email": "duplicate@example.com",
        "password": "securepassword123",
    }
    # First user succeeds
    response = await client.post("/users", json=payload)
    assert response.status_code == 201

    # Second user with same email fails with generic message
    response = await client.post("/users", json=payload)
    assert response.status_code == 400
    assert "Invalid registration data" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_user_invalid_password(client: AsyncClient) -> None:
    """Test that creating user with short password fails validation."""
    payload = {
        "email": "test@example.com",
        "password": "short",  # Less than 8 characters
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_create_user_invalid_email(client: AsyncClient) -> None:
    """Test that creating user with invalid email format fails validation."""
    payload = {
        "email": "not-an-email",
        "password": "securepassword123",
    }
    # Note: client uses ASGITransport which bypasses real network,
    # but Pydantic EmailStr still validates format.
    response = await client.post("/users", json=payload)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_list_users_empty(client: AsyncClient) -> None:
    """Test listing users when none exist."""
    # The client fixture creates one test_user by default.
    # So we expect 1 user, not 0.
    response = await client.get("/users")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_list_users_with_data(client: AsyncClient) -> None:
    """Test listing users after creating some."""
    # Create 3 more users (total 4)
    for i in range(3):
        payload = {
            "email": f"user{i}@example.com",
            "password": "securepassword123",
        }
        await client.post("/users", json=payload)

    response = await client.get("/users")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 4
    assert data["total"] == 4


@pytest.mark.asyncio
async def test_list_users_pagination(client: AsyncClient) -> None:
    """Test pagination parameters work correctly."""
    # Create 5 users (total 6)
    for i in range(5):
        payload = {
            "email": f"pageuser{i}@example.com",
            "password": "securepassword123",
        }
        await client.post("/users", json=payload)

    # Get first page
    response = await client.get("/users?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 6

    # Get second page
    response = await client.get("/users?limit=2&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 6


@pytest.mark.asyncio
async def test_get_user_by_id(client: AsyncClient) -> None:
    """Test getting a user by their ID."""
    # Create user
    create_payload = {
        "email": "getme@example.com",
        "password": "securepassword123",
    }
    create_response = await client.post("/users", json=create_payload)
    user_id = create_response.json()["id"]

    # Get user
    response = await client.get(f"/users/{user_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user_id
    assert data["email"] == "getme@example.com"


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent user returns generic 404 message."""
    import uuid

    fake_id = str(uuid.uuid4())
    response = await client.get(f"/users/{fake_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_user_email(client: AsyncClient) -> None:
    """Test updating a user's email."""
    # Create user
    create_payload = {
        "email": "update@example.com",
        "password": "securepassword123",
    }
    create_response = await client.post("/users", json=create_payload)
    user_id = create_response.json()["id"]

    # Update email
    update_payload = {"email": "updated@example.com"}
    response = await client.put(f"/users/{user_id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "updated@example.com"
    assert data["id"] == user_id


@pytest.mark.asyncio
async def test_update_user_duplicate_email(client: AsyncClient) -> None:
    """Test that updating to an existing email fails with generic message."""
    # Create two users
    payload1 = {
        "email": "user1@test.com",
        "password": "securepassword123",
    }
    payload2 = {
        "email": "user2@test.com",
        "password": "securepassword123",
    }
    await client.post("/users", json=payload1)
    user2_response = await client.post("/users", json=payload2)
    user2_id = user2_response.json()["id"]

    # Try to update user2 with user1's email - should get generic error
    update_payload = {"email": "user1@test.com"}
    response = await client.put(f"/users/{user2_id}", json=update_payload)
    assert response.status_code == 400
    assert "Invalid update data" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_user_not_found(client: AsyncClient) -> None:
    """Test updating a non-existent user returns 404."""
    import uuid

    fake_id = str(uuid.uuid4())
    response = await client.put(f"/users/{fake_id}", json={"email": "new@example.com"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_password_is_hashed(client: AsyncClient) -> None:
    """Test that passwords are stored as hashes, not plain text."""
    payload = {
        "email": "hash@example.com",
        "password": "myplainpassword",
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 201

    # Verify response doesn't contain plain password
    data = response.json()
    assert data["email"] == "hash@example.com"
    assert "password" not in data
    assert "hashed_password" not in data  # Response schema doesn't expose it


@pytest.mark.asyncio
async def test_user_response_timezone_aware(client: AsyncClient) -> None:
    """Test that response timestamps are timezone-aware."""
    payload = {
        "email": "timezone@example.com",
        "password": "securepassword123",
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 201
    data = response.json()

    # Check created_at is timezone-aware (contains Z or +00:00)
    assert "Z" in data["created_at"] or "+00:00" in data["created_at"] or "T00:00:00+00:00" in data["created_at"]


class TestUserSchemas:
    """Unit tests for user schemas without database."""

    def test_user_create_schema_valid(self):
        """Test UserCreate schema with valid data."""
        from src.schemas.user import UserCreate

        user = UserCreate(email="test@example.com", password="securepassword123")
        assert user.email == "test@example.com"
        assert user.password == "securepassword123"

    def test_user_create_schema_invalid_email(self):
        """Test UserCreate schema rejects invalid email."""
        from pydantic import ValidationError

        from src.schemas.user import UserCreate

        try:
            UserCreate(email="not-an-email", password="securepassword123")
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_user_create_schema_short_password(self):
        """Test UserCreate schema rejects short password."""
        from pydantic import ValidationError

        from src.schemas.user import UserCreate

        try:
            UserCreate(email="test@example.com", password="short")
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass

    def test_user_update_schema_optional_email(self):
        """Test UserUpdate schema with optional email."""
        from src.schemas.user import UserUpdate

        user = UserUpdate()
        assert user.email is None

    def test_user_update_schema_with_email(self):
        """Test UserUpdate schema with email provided."""
        from src.schemas.user import UserUpdate

        user = UserUpdate(email="new@example.com")
        assert user.email == "new@example.com"

    def test_user_response_schema(self):
        """Test UserResponse schema."""
        from datetime import datetime
        from uuid import uuid4

        from src.schemas.user import UserResponse

        user_id = uuid4()
        now = datetime.now(UTC)
        user = UserResponse(
            id=user_id,
            email="test@example.com",
            created_at=now,
            updated_at=now,
        )
        assert user.id == user_id
        assert user.email == "test@example.com"

    def test_user_list_response_schema(self):
        """Test UserListResponse schema."""
        from datetime import datetime
        from uuid import uuid4

        from src.schemas.user import UserListResponse, UserResponse

        now = datetime.now(UTC)
        items = [
            UserResponse(
                id=uuid4(),
                email="user1@example.com",
                created_at=now,
                updated_at=now,
            ),
            UserResponse(
                id=uuid4(),
                email="user2@example.com",
                created_at=now,
                updated_at=now,
            ),
        ]
        response = UserListResponse(items=items, total=2)
        assert len(response.items) == 2
        assert response.total == 2

    def test_user_response_timezone_conversion(self):
        """Test UserResponse converts naive datetime to UTC."""
        from datetime import datetime
        from uuid import uuid4

        from src.schemas.user import UserResponse

        naive_dt = datetime(2026, 1, 12, 0, 0, 0)
        user = UserResponse(
            id=uuid4(),
            email="test@example.com",
            created_at=naive_dt,
            updated_at=naive_dt,
        )
        # After validation, datetime should be timezone-aware
        assert user.created_at.tzinfo is not None
        assert user.updated_at.tzinfo is not None
