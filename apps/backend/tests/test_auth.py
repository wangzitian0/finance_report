"""Tests for authentication dependency."""

import pytest
from uuid import uuid4
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_auth_missing_header(db_engine):
    """Test 401 when X-User-Id header is missing."""
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-User-Id header"

@pytest.mark.asyncio
async def test_auth_invalid_uuid(db_engine):
    """Test 401 when X-User-Id is not a valid UUID."""
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, 
        base_url="http://test",
        headers={"X-User-Id": "not-a-uuid"}
    ) as ac:
        response = await ac.get("/api/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid X-User-Id format"

@pytest.mark.asyncio
async def test_auth_non_existent_user(db_engine):
    """Test 401 when X-User-Id is a valid UUID but user does not exist."""
    from src.main import app
    transport = ASGITransport(app=app)
    random_uuid = str(uuid4())
    async with AsyncClient(
        transport=transport, 
        base_url="http://test",
        headers={"X-User-Id": random_uuid}
    ) as ac:
        response = await ac.get("/api/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid user"

@pytest.mark.asyncio
async def test_auth_valid_user(client, test_user):
    """Test 200 when valid X-User-Id is provided."""
    # The client fixture already has the valid test_user.id in headers
    response = await client.get("/api/accounts")
    assert response.status_code == 200
