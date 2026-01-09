"""Backend tests."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database import Base, get_db
from src.main import app


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
async def cleanup_resources() -> AsyncGenerator[None, None]:
    """Cleanup resources after all tests."""
    yield
    await test_engine.dispose()


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Override database dependency for tests."""
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
async def mock_init_db() -> AsyncGenerator[None, None]:
    """Mock init_db to prevent real DB connection during lifespan."""
    # Patch the init_db imported in main.py
    with patch("src.main.init_db", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture(autouse=True)
async def setup_database() -> AsyncGenerator[None, None]:
    """Create tables before each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async test client with test database."""
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_health(client: AsyncClient) -> None:
    """Test health endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


async def test_ping_initial_state(client: AsyncClient) -> None:
    """Test initial ping state."""
    response = await client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ping"
    assert data["toggle_count"] == 0
    assert data["last_toggled"] is None


async def test_ping_toggle(client: AsyncClient) -> None:
    """Test toggle endpoint."""
    # First toggle - should go from ping to pong
    response = await client.post("/ping/toggle")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "pong"
    assert data["toggle_count"] == 1
    assert "last_toggled" in data

    # Second toggle - should go back to ping
    response = await client.post("/ping/toggle")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ping"
    assert data["toggle_count"] == 2
