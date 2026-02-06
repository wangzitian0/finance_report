"""Integration tests for Auth Router."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.routers.auth import hash_password


@pytest.mark.asyncio
async def test_register_success(public_client):
    """AC1.7.1: Test successful user registration."""
    payload = {"email": "newuser@example.com", "password": "password123", "name": "New User"}
    response = await public_client.post("/auth/register", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["name"] == "New User"
    assert "id" in data
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(db: AsyncSession, public_client):
    """AC1.7.2: Test registration failure with duplicate email."""
    # Pre-create user
    user = User(email="existing@example.com", hashed_password=hash_password("password123"))
    db.add(user)
    await db.commit()

    payload = {"email": "existing@example.com", "password": "password123"}
    response = await public_client.post("/auth/register", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_login_success(db: AsyncSession, public_client):
    """AC1.7.3: Test successful login with valid credentials."""
    password = "secretpassword"
    hashed = hash_password(password)
    user = User(email="loginuser@example.com", hashed_password=hashed)
    db.add(user)
    await db.commit()

    payload = {"email": "loginuser@example.com", "password": password}
    response = await public_client.post("/auth/login", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "loginuser@example.com"
    assert data["id"] == str(user.id)
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_password(db: AsyncSession, public_client):
    """Test login with wrong password."""
    user = User(email="wrongpass@example.com", hashed_password=hash_password("correctpass"))
    db.add(user)
    await db.commit()

    payload = {"email": "wrongpass@example.com", "password": "wrongpassword"}
    response = await public_client.post("/auth/login", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_login_non_existent_user(public_client):
    """Test login with non-existent user."""
    payload = {"email": "ghost@example.com", "password": "password123"}
    response = await public_client.post("/auth/login", json=payload)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_success(client, test_user):
    """Test get current user endpoint."""
    # client fixture already includes X-User-Id for test_user
    response = await client.get("/auth/me")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(test_user.id)
    assert data["email"] == test_user.email


@pytest.mark.asyncio
async def test_get_me_user_not_found(public_client):
    """Test /auth/me with non-existent user ID returns 401."""
    from src.security import create_access_token

    # Use a random UUID that doesn't exist in DB
    user_id = "00000000-0000-0000-0000-000000000000"
    token = create_access_token(data={"sub": user_id})
    headers = {"Authorization": f"Bearer {token}"}
    response = await public_client.get("/auth/me", headers=headers)

    # Dependency returns 401 for non-existent user
    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"
