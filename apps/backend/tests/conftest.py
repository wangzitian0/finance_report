"""Test fixtures and configuration."""

import os
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


# --- Helper to ensure 127.0.0.1 consistency ---
def normalize_url(url: str | None) -> str | None:
    if url and "localhost" in url:
        return url.replace("localhost", "127.0.0.1")
    return url


# Database setup
TEST_DATABASE_URL = (
    normalize_url(
        os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test",
        )
    )
    or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test"
)

# S3 setup
os.environ["S3_ENDPOINT"] = (
    normalize_url(os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9000")) or "http://127.0.0.1:9000"
)
os.environ["REDIS_URL"] = (
    normalize_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    or "redis://127.0.0.1:6379/0"
)

# Set ENVIRONMENT for pydantic settings
os.environ["ENVIRONMENT"] = "testing"


async def ensure_database():
    """Ensure the test database exists."""
    url = make_url(TEST_DATABASE_URL)
    db_name = url.database

    # Connect to 'postgres' database to check/create test db
    # Must run in AUTOCOMMIT mode to create database
    default_url = url.set(database="postgres")
    engine = create_async_engine(default_url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
            )
            if not result.scalar():
                print(f"Creating test database: {db_name}")
                await conn.execute(text(f"CREATE DATABASE {db_name}"))
            else:
                print(f"Test database {db_name} already exists")
    except Exception as e:
        print(f"Warning: Failed to ensure database exists: {e}")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a test database engine."""
    await ensure_database()

    from src.database import Base
    from src.models import (  # noqa: F401
        Account,
        BankStatement,
        BankStatementTransaction,
        ChatMessage,
        ChatSession,
        FxRate,
        JournalEntry,
        JournalLine,
        PingState,
        ReconciliationMatch,
        User,
    )

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        # Ensure clean slate
        await conn.run_sync(Base.metadata.drop_all)
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
async def test_user(db: AsyncSession):
    """Create a test user for authenticated requests."""
    from src.models import User

    user = User(
        email=f"test-{uuid4()}@example.com",
        hashed_password="hashed",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def client(db_engine, test_user):
    """Create async test client with database initialized."""
    # Override the database URL for the app
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    # Monkeypatch the session maker to use our test engine
    # This ensures that even if dependency override fails, the app uses the test DB
    from src import database

    original_maker = database.async_session_maker

    test_maker = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    database.async_session_maker = test_maker

    async def override_get_db():
        async with test_maker() as session:
            yield session

    # Import app after setting env var
    from src.database import get_db
    from src.main import app
    from src.security import create_access_token

    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(data={"sub": str(test_user.id)})
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client
    finally:
        # Restore original session maker
        database.async_session_maker = original_maker
        # Only remove the override we added, not others
        app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture(scope="function")
async def public_client(db_engine):
    """Create async test client without auth headers."""
    # Override the database URL for the app
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    # Monkeypatch session maker
    from src import database

    original_maker = database.async_session_maker

    test_maker = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    database.async_session_maker = test_maker

    async def override_get_db():
        async with test_maker() as session:
            yield session

    # Import app after setting env var
    from src.database import get_db
    from src.main import app

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client
    finally:
        database.async_session_maker = original_maker
        # Only remove the override we added, not others
        app.dependency_overrides.pop(get_db, None)
