"""Test fixtures and configuration."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Container configuration
CONTAINER_RUNTIME = os.getenv("CONTAINER_RUNTIME", "podman")
POSTGRES_IMAGE = "postgres:15-alpine"
CONTAINER_PREFIX = "fr_test"


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_postgres(port: int, timeout: int = 30) -> bool:
    """Wait for PostgreSQL to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(("localhost", port))
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.5)
    return False


def _container_running(name: str) -> bool:
    """Check if container is running."""
    result = subprocess.run(
        [CONTAINER_RUNTIME, "ps", "-q", "-f", f"name=^{name}$"],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())


@pytest.fixture(scope="session")
def test_db_container():
    """Auto-start ephemeral test database container.
    
    In CI (GitHub Actions): Uses the service container on port 5432.
    Locally: Starts an ephemeral container with tmpfs for fast testing.
    """
    # Check if we're in CI or if DATABASE_URL is already set externally
    if os.getenv("CI") or os.getenv("DATABASE_URL"):
        # CI environment or external database - use configured URL
        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report_test"
        )
        os.environ["DATABASE_URL"] = db_url
        yield db_url
        return
    
    # Check if dev container is already running
    dev_container = "fr_dev_db"
    if _container_running(dev_container):
        # Use existing dev container
        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report_test"
        os.environ["DATABASE_URL"] = db_url
        
        # Ensure test database exists
        subprocess.run([
            CONTAINER_RUNTIME, "exec", dev_container,
            "psql", "-U", "postgres", "-c",
            "CREATE DATABASE finance_report_test",
        ], capture_output=True)
        
        yield db_url
        return
    
    # Start ephemeral test container
    container_name = f"{CONTAINER_PREFIX}_{os.getpid()}"
    port = _find_free_port()
    
    print(f"\n🔄 Starting ephemeral database: {container_name} on port {port}")
    
    result = subprocess.run([
        CONTAINER_RUNTIME, "run", "-d", "--rm",
        "--name", container_name,
        "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m",
        "-p", f"{port}:5432",
        "-e", "POSTGRES_PASSWORD=postgres",
        "-e", "POSTGRES_DB=finance_report_test",
        POSTGRES_IMAGE,
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Failed to start container: {result.stderr}", file=sys.stderr)
        pytest.skip("Could not start test database container")
    
    if not _wait_for_postgres(port, timeout=30):
        subprocess.run([CONTAINER_RUNTIME, "stop", container_name], capture_output=True)
        pytest.skip("Database did not become ready in time")
    
    db_url = f"postgresql+asyncpg://postgres:postgres@localhost:{port}/finance_report_test"
    os.environ["DATABASE_URL"] = db_url
    
    print(f"✅ Database ready: {db_url}")
    
    yield db_url
    
    # Cleanup
    print(f"\n🧹 Stopping ephemeral database: {container_name}")
    subprocess.run([CONTAINER_RUNTIME, "stop", container_name], capture_output=True)


@pytest_asyncio.fixture(scope="function")
async def db_engine(test_db_container):
    """Create a test database engine."""
    from src.database import Base

    engine = create_async_engine(
        test_db_container,
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
async def client(db_engine, test_db_container):
    """Create async test client with database initialized."""
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
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
