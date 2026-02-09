"""AC1.7.1 - AC1.7.1: Authentication Logic Tests

These tests validate JWT token-based authentication, user existence checks,
and invalid credential scenarios including token validation and session management.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_user_id


@pytest.mark.asyncio
async def test_auth_missing_header(db_engine):
    """Test 401 when Authorization header is missing."""
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_auth_invalid_token(db_engine):
    """Test 401 when Authorization token is invalid."""
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer invalid-token"},
    ) as ac:
        response = await ac.get("/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


@pytest.mark.asyncio
async def test_auth_non_existent_user(db_engine):
    """Test 401 when JWT is valid but user does not exist."""
    from src.main import app
    from src.security import create_access_token

    transport = ASGITransport(app=app)
    random_uuid = str(uuid4())
    token = create_access_token(data={"sub": random_uuid})
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as ac:
        response = await ac.get("/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"


@pytest.mark.asyncio
async def test_auth_valid_user(client, test_user):
    """Test 200 when valid JWT is provided."""
    # The client fixture already has the valid JWT in headers
    response = await client.get("/accounts")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_current_user_id_direct(db, test_user):
    """Directly resolve a valid user from JWT token payload."""
    from src.security import create_access_token

    token = create_access_token(data={"sub": str(test_user.id)})
    user_id = await get_current_user_id(token=token, db=db)
    assert user_id == test_user.id


@pytest.mark.asyncio
async def test_get_current_user_id_invalid_user_db(db):
    """Database-backed invalid user should raise 401."""
    from src.security import create_access_token

    token = create_access_token(data={"sub": str(uuid4())})
    with pytest.raises(HTTPException, match="User not found"):
        await get_current_user_id(token=token, db=db)
