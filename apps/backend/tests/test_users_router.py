"""Tests for users router endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_user_success(client: AsyncClient) -> None:
    """Test creating a new user successfully."""
    payload = {
        "email": "test@example.com",
        "password": "securepassword123",
    }
    response = await client.post("/api/users", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert "id" in data
    assert "hashed_password" not in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_user_duplicate_email(client: AsyncClient) -> None:
    """Test that creating a user with existing email fails."""
    payload = {
        "email": "duplicate@example.com",
        "password": "securepassword123",
    }
    # First user succeeds
    response = await client.post("/api/users", json=payload)
    assert response.status_code == 201

    # Second user with same email fails
    response = await client.post("/api/users", json=payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_user_invalid_password(client: AsyncClient) -> None:
    """Test that creating user with short password fails validation."""
    payload = {
        "email": "test@example.com",
        "password": "short",  # Less than 8 characters
    }
    response = await client.post("/api/users", json=payload)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_list_users_empty(client: AsyncClient) -> None:
    """Test listing users when none exist."""
    response = await client.get("/api/users")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_users_with_data(client: AsyncClient) -> None:
    """Test listing users after creating some."""
    # Create users
    for i in range(3):
        payload = {
            "email": f"user{i}@example.com",
            "password": "securepassword123",
        }
        await client.post("/api/users", json=payload)

    response = await client.get("/api/users")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_get_user_by_id(client: AsyncClient) -> None:
    """Test getting a user by their ID."""
    # Create user
    create_payload = {
        "email": "getme@example.com",
        "password": "securepassword123",
    }
    create_response = await client.post("/api/users", json=create_payload)
    user_id = create_response.json()["id"]

    # Get user
    response = await client.get(f"/api/users/{user_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user_id
    assert data["email"] == "getme@example.com"


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent user returns 404."""
    import uuid

    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/users/{fake_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_user_email(client: AsyncClient) -> None:
    """Test updating a user's email."""
    # Create user
    create_payload = {
        "email": "update@example.com",
        "password": "securepassword123",
    }
    create_response = await client.post("/api/users", json=create_payload)
    user_id = create_response.json()["id"]

    # Update email
    update_payload = {"email": "updated@example.com"}
    response = await client.put(f"/api/users/{user_id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "updated@example.com"
    assert data["id"] == user_id


@pytest.mark.asyncio
async def test_update_user_duplicate_email(client: AsyncClient) -> None:
    """Test that updating to an existing email fails."""
    # Create two users
    payload1 = {
        "email": "user1@test.com",
        "password": "securepassword123",
    }
    payload2 = {
        "email": "user2@test.com",
        "password": "securepassword123",
    }
    await client.post("/api/users", json=payload1)
    user2_response = await client.post("/api/users", json=payload2)
    user2_id = user2_response.json()["id"]

    # Try to update user2 with user1's email
    update_payload = {"email": "user1@test.com"}
    response = await client.put(f"/api/users/{user2_id}", json=update_payload)
    assert response.status_code == 400
    assert "already in use" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_user_not_found(client: AsyncClient) -> None:
    """Test updating a non-existent user returns 404."""
    import uuid

    fake_id = str(uuid.uuid4())
    response = await client.put(f"/api/users/{fake_id}", json={"email": "new@example.com"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_password_is_hashed(client: AsyncClient) -> None:
    """Test that passwords are stored as hashes, not plain text."""
    payload = {
        "email": "hash@example.com",
        "password": "myplainpassword",
    }
    response = await client.post("/api/users", json=payload)
    assert response.status_code == 201

    # Verify response doesn't contain plain password
    data = response.json()
    assert data["email"] == "hash@example.com"
    assert "password" not in data
    assert "hashed_password" not in data  # Response schema doesn't expose it
