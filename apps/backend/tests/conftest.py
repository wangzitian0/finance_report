"""Test fixtures and configuration."""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.logger import get_logger
from src.services.fx import clear_fx_cache

logger = get_logger(__name__)


# --- Bootloader Mock ---
# Prevent Bootloader from creating its own engine (causes event loop conflicts)
@pytest.fixture(autouse=True)
def mock_bootloader_db_check():
    """Mock Bootloader._check_database to avoid event loop conflicts in tests."""
    from src.boot import ServiceStatus

    async def mock_check():
        return ServiceStatus("database", "ok", "Mocked for tests", 0.0)

    with patch("src.boot.Bootloader._check_database", new=mock_check):
        yield


# --- FX Cache Cleanup ---
@pytest.fixture(autouse=True)
def cleanup_fx_cache():
    """Clear FX cache before and after each test to ensure isolation."""
    try:
        clear_fx_cache()
    except Exception as e:
        logger.warning(
            "FX cache pre-test cleanup failed",
            error=str(e),
            error_type=type(e).__name__,
        )
    yield
    try:
        clear_fx_cache()
    except Exception as e:
        logger.warning(
            "FX cache post-test cleanup failed",
            error=str(e),
            error_type=type(e).__name__,
        )


# --- Helper to ensure 127.0.0.1 consistency ---
def normalize_url(url: str | None) -> str | None:
    """Normalize localhost to 127.0.0.1 for consistent database connections.

    Some PostgreSQL client libraries and Docker networking treat 'localhost'
    and '127.0.0.1' as different hosts, which can cause connection pool issues
    or routing conflicts in pytest-xdist parallel execution.

    This ensures all tests use the same hostname format for consistency.
    """
    if url and "localhost" in url:
        return url.replace("localhost", "127.0.0.1")
    return url


# --- pytest-xdist worker isolation ---
@pytest.fixture(scope="session")
def worker_id(request):
    """Get pytest-xdist worker ID if running in parallel."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["workerid"]
    return "master"


def get_test_db_url(worker_id: str) -> str:
    """Generate database URL specific to pytest-xdist worker.

    Args:
        worker_id: Worker identifier ('master' for serial, 'gw0'/'gw1'/... for parallel)

    Returns:
        Database URL with worker-specific database name for parallel execution
    """
    base_url = (
        normalize_url(
            os.environ.get(
                "DATABASE_URL",
                "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test",
            )
        )
        or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test"
    )

    if worker_id != "master":
        url_obj = make_url(base_url)
        worker_db_name = f"{url_obj.database}_{worker_id}"
        new_url = url_obj.set(database=worker_db_name)
        return new_url.render_as_string(hide_password=False)

    return base_url


# Database setup - support pytest-xdist parallel execution
@pytest.fixture(scope="session")
def test_database_url(worker_id):
    """Get worker-specific test database URL."""
    return get_test_db_url(worker_id)


# Maintain backward compatibility for fixtures that don't use worker_id
TEST_DATABASE_URL = get_test_db_url("master")

# S3 setup
os.environ["S3_ENDPOINT"] = (
    normalize_url(os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9000")) or "http://127.0.0.1:9000"
)

# Redis is optional (only for distributed rate limiting in production)
# Do not set default - let tests run without Redis
if "REDIS_URL" in os.environ:
    os.environ["REDIS_URL"] = normalize_url(os.environ["REDIS_URL"]) or os.environ["REDIS_URL"]

# Set ENVIRONMENT for pydantic settings
os.environ["ENVIRONMENT"] = "testing"


# --- Structlog Configuration for Tests ---
@pytest.fixture(autouse=True, scope="session")
def configure_structlog_for_tests():
    """Configure structlog for proper capsys capture in tests."""
    try:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]

        structlog.configure(
            processors=processors,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=False,
        )

        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=processors[:-1],
        )

        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)
    except Exception as e:
        logging.basicConfig(level=logging.DEBUG)
        logging.error(f"CRITICAL: Structlog configuration failed: {e}", exc_info=True)

    yield

    try:
        structlog.reset_defaults()
    except Exception as e:
        logging.warning(f"Structlog reset failed: {e}")


async def ensure_database(db_url: str):
    """Ensure the test database exists, creating it if necessary.

    Args:
        db_url: Full database URL including worker-specific database name
                (e.g., finance_report_test_gw0 for pytest-xdist worker 0)

    Implementation:
        1. Connects to 'postgres' default database
        2. Uses AUTOCOMMIT isolation level (required for CREATE DATABASE DDL)
        3. Checks if test database exists via pg_database catalog
        4. Creates database if missing

    Error Handling:
        - SQLAlchemyError: Raises RuntimeError to fail test run immediately
        - Non-SQL errors: Raises RuntimeError to fail test run immediately
    """
    url = make_url(db_url)
    db_name = url.database

    default_url = url.set(database="postgres")
    engine = create_async_engine(default_url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            if not result.scalar():
                print(f"Creating test database: {db_name}")
                await conn.execute(text(f"CREATE DATABASE {db_name}"))
            else:
                print(f"Test database {db_name} already exists")
    except (SQLAlchemyError, Exception) as e:
        worker_id = db_name.split("_")[-1] if db_name and "_" in db_name else "master"
        logger.error(
            "Test database setup failed",
            database=db_name,
            error=str(e),
            error_type=type(e).__name__,
            worker_id=worker_id,
        )

        if isinstance(e, SQLAlchemyError):
            raise RuntimeError(f"Cannot proceed without test database (SQLAlchemy): {e}") from e
        else:
            raise RuntimeError(f"Cannot proceed without test database (Connection): {e}") from e
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def db_engine(test_database_url, tmp_path_factory, worker_id):
    """Create a test database engine with worker-specific isolation.

    Session-scoped: Creates database schema once per pytest-xdist worker, not
    per test. Schema creation involves expensive DDL operations (CREATE TABLE,
    CREATE INDEX, etc.) and cascade drops of all existing tables. By doing this
    once per worker session, we reduce test suite execution time by 70-80%
    compared to function-scoped schema recreation.

    Tradeoffs:
        - Fast: Schema created once per worker (~100ms vs ~5ms per test)
        - Safe: Individual test isolation via transaction rollback (see db fixture)
        - Risk: Shared schema state if transactions leak (prevented by rollback)

    Technical Details:
        - Uses NullPool to prevent connection pool conflicts in test environment
        - Worker isolation via pytest-xdist (each worker gets separate database)
        - Clean slate ensured by CASCADE drops at session start and end
        - All tables created via Base.metadata.create_all
        - File-based locking prevents race conditions during schema setup

    See: db fixture for transaction rollback pattern
    """
    await ensure_database(test_database_url)

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

    # Each worker gets its own database, so no locking needed across workers.
    # The lock file is ONLY for protecting against concurrent pytest-xdist
    # workers trying to create the SAME database (shouldn't happen with worker_id
    # in the database name, but kept as defensive programming).
    root_tmp_dir = tmp_path_factory.getbasetemp().parent
    lock_file = root_tmp_dir / f"db_setup_{worker_id}.lock"

    # Acquire lock ONLY during schema creation
    lock_acquired = False
    try:
        lock_file.touch(exist_ok=False)
        lock_acquired = True
    except FileExistsError:
        for i in range(10):
            time.sleep(0.5)
            if not lock_file.exists():
                try:
                    lock_file.touch(exist_ok=False)
                    lock_acquired = True
                    break
                except FileExistsError:
                    continue
        if not lock_acquired:
            logger.error(
                "Schema setup lock timeout",
                worker_id=worker_id,
                lock_file=str(lock_file),
                waited_seconds=5,
            )
            raise RuntimeError(
                f"Worker {worker_id}: Schema setup lock timed out after 5s. "
                f"Another worker may have crashed during setup."
            )

    engine = None
    try:
        engine = create_async_engine(
            test_database_url,
            echo=False,
            poolclass=NullPool,
        )

        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.error(
            "Schema setup failed",
            worker_id=worker_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        if engine:
            try:
                await engine.dispose()
            except Exception:
                pass
        raise
    finally:
        # Release lock IMMEDIATELY after schema creation
        if lock_acquired:
            lock_file.unlink(missing_ok=True)

    yield engine

    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    except Exception as e:
        logger.error(
            "CRITICAL: Schema cleanup failed - subsequent tests may fail",
            worker_id=worker_id,
            error=str(e),
            error_type=type(e).__name__,
            database_url=test_database_url,
        )

    try:
        await asyncio.wait_for(engine.dispose(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error(
            "CRITICAL: Engine disposal timed out - connections may be leaked",
            worker_id=worker_id,
        )
        await engine.dispose(close=True)
    except Exception as e:
        logger.error(
            "Engine disposal failed",
            error=str(e),
            error_type=type(e).__name__,
        )


@pytest_asyncio.fixture(scope="function", autouse=True)
async def patch_database_connection(db_engine):
    """Override global database session maker to use test engine.

    Ensures API handlers use test database. For tests using the db fixture,
    the session maker will be further overridden to bind to the test
    transaction connection (see db fixture implementation).
    """
    from src import database

    test_maker = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    database.set_test_session_maker(test_maker)
    yield
    database.set_test_session_maker(None)


@pytest_asyncio.fixture(scope="function")
async def db(db_engine, request):
    """Create a test database session with transaction rollback for isolation.

    Each test runs within a database transaction that is rolled back after
    completion, discarding all changes. This provides complete test isolation
    without recreating database schema, reducing per-test overhead from ~100ms
    to ~5ms.

    How it works:
        1. Opens a connection from db_engine (shared schema)
        2. Starts a transaction on that connection
        3. Binds an AsyncSession to the connection within the transaction
        4. Test runs and makes database changes
        5. After test: session closed → transaction rolled back → changes discarded

    Technical Details:
        - expire_on_commit=False: Prevents lazy-loading errors after rollback
        - Transaction isolation: Even if test calls db.commit(), outer transaction
          still rolls back, ensuring no data leaks between tests
        - Cleanup order: session.close() → transaction.rollback() → connection.close()

    Performance:
        - Function-scoped: New transaction per test (~5ms overhead)
        - Alternative (function-scoped db_engine): ~100ms per test (20x slower)

    Limitations:
        - Does not test COMMIT behavior (commits happen within transaction)
        - Does not test connection pool behavior (uses direct connection)
    """
    test_name = request.node.name

    try:
        connection = await db_engine.connect()
    except Exception as e:
        logger.error(
            "Failed to acquire database connection",
            test_name=test_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise RuntimeError(f"Test setup failed: cannot acquire database connection: {e}") from e

    try:
        if connection.closed:
            raise RuntimeError("Acquired connection is already closed")

        transaction = await connection.begin()
    except Exception as e:
        logger.error(
            "Failed to begin transaction",
            test_name=test_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        await connection.close()
        raise RuntimeError(f"Test setup failed: cannot begin transaction: {e}") from e

    session = AsyncSession(bind=connection, expire_on_commit=False)

    yield session

    try:
        await session.close()
    except Exception as e:
        logger.error(
            "Test session close failed",
            test_name=test_name,
            error=str(e),
            error_type=type(e).__name__,
        )

    try:
        await transaction.rollback()
    except Exception as e:
        logger.error(
            "CRITICAL: Transaction rollback failed - test isolation compromised",
            test_name=test_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise RuntimeError(f"Test {test_name}: transaction rollback failed: {e}") from e
    finally:
        try:
            await connection.close()
        except Exception as e:
            logger.warning(
                "Connection close failed during cleanup",
                test_name=test_name,
                error=str(e),
                error_type=type(e).__name__,
            )


@pytest_asyncio.fixture(scope="function")
async def test_user(db_engine, request):
    """Create a test user for authenticated requests.

    Creates user by committing directly to database (not within test transaction).
    This is necessary because:
    - API handlers spawn background tasks with separate database sessions
    - Background tasks can't share transaction-bound connections (asyncpg limitation)
    - User must be visible to all sessions, not just within a transaction

    Cleanup: Explicitly deletes user after test to ensure test isolation.
    """
    from src.models import User

    test_name = request.node.name

    # Create user with separate engine-bound session (commits to DB)
    async with AsyncSession(db_engine, expire_on_commit=False) as user_session:
        user = User(
            email=f"test-{uuid4()}@example.com",
            hashed_password="hashed",
        )
        user_session.add(user)

        try:
            await user_session.commit()
            await user_session.refresh(user)
            user_id = user.id  # Capture ID before session closes
        except Exception as e:
            logger.error(
                "Failed to create test user",
                test_name=test_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            await user_session.rollback()
            raise RuntimeError(f"Test setup failed: cannot create test user: {e}") from e

    yield user

    # Cleanup: Delete user explicitly to ensure test isolation
    async with AsyncSession(db_engine, expire_on_commit=False) as cleanup_session:
        try:
            from sqlalchemy import delete
            from src.models import User

            await cleanup_session.execute(delete(User).where(User.id == user_id))
            await cleanup_session.commit()
        except Exception as e:
            logger.warning(
                "Test user cleanup failed",
                test_name=test_name,
                user_id=str(user_id),
                error=str(e),
                error_type=type(e).__name__,
            )


@pytest_asyncio.fixture(scope="function")
async def client(db_engine, test_user):
    """Create async test client with database initialized."""
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    from src.main import app
    from src.security import create_access_token

    token = create_access_token(data={"sub": str(test_user.id)})
    client_instance = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client_instance:
            yield client_instance
    except Exception as e:
        logger.error(
            "Test client creation or execution failed",
            error=str(e),
            error_type=type(e).__name__,
            test_user_id=str(test_user.id),
        )
        raise
    finally:
        if client_instance is not None:
            try:
                await asyncio.wait_for(client_instance.aclose(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Test client close timed out")
            except Exception as e:
                logger.warning(
                    "Test client cleanup failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )


@pytest_asyncio.fixture(scope="function")
async def public_client(db_engine):
    """Create async test client without auth headers."""
    # Override the database URL for the app
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    # Create test session maker bound to test engine
    test_maker = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Inject test session maker via explicit hook
    from src import database

    database.set_test_session_maker(test_maker)

    # Import app after setting env var
    from src.main import app

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client
    finally:
        # Reset session maker
        database.set_test_session_maker(None)
