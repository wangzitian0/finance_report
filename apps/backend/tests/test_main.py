"""Backend tests."""

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.fixture
async def client():
    """Async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    """Test health endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_ping_initial_state(client: AsyncClient):
    """Test initial ping state."""
    response = await client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] in ["ping", "pong"]
    assert "toggle_count" in data
