"""Backend tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client() -> AsyncClient:
    """Async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    """Test health endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_ping_initial_state(client: AsyncClient) -> None:
    """Test initial ping state."""
    response = await client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] in ["ping", "pong"]
    assert "toggle_count" in data


@pytest.mark.asyncio
async def test_ping_toggle(client: AsyncClient) -> None:
    """Test toggle endpoint."""
    # Get initial state
    response = await client.get("/ping")
    assert response.status_code == 200
    initial_data = response.json()
    initial_state = initial_data["state"]
    initial_count = initial_data["toggle_count"]

    # Toggle state
    response = await client.post("/ping/toggle")
    assert response.status_code == 200
    data = response.json()

    # State should be toggled
    expected_state = "pong" if initial_state == "ping" else "ping"
    assert data["state"] == expected_state
    assert data["toggle_count"] == initial_count + 1
    assert "last_toggled" in data
