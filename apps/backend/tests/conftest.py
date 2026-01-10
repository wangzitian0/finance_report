"""Test fixtures and configuration."""

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Use test database from docker-compose
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a test database engine."""
    from src.database import Base

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db(db_engine):
    """Create a test database session.

    Note: The db_engine fixture handles table cleanup by dropping all tables
    after each test. The rollback here handles any uncommitted changes.
    """
    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        # Rollback any uncommitted changes (committed data cleaned by db_engine)
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_engine):
    """Create async test client with database initialized."""
    # Override the database URL for the app
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with async_session() as session:
            yield session

    # Import app after setting env var
    from src.database import get_db
    from src.main import app

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
