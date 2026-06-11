"""Test fixtures and configuration."""

import logging
import os
import sys
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

from src.config import settings
from src.logger import get_logger
from src.services.fx import clear_fx_cache

logger = get_logger(__name__)


# --- AC behavioral-evidence emission ---
# Lets a backend test attach a measured (code, score, metric, comment,
# provenance) record per AC to its junit result. The repo-root path is appended
# lazily *inside* the fixture so only tests that opt in can import ``common``;
# the rest of the backend suite is unaffected.
@pytest.fixture
def ac_evidence(record_property):
    """Return an emitter: ac_evidence(ac_id=..., score=..., metric=..., ...)."""
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parents[3])
    if repo_root not in sys.path:
        # Insert at the front so the repo's `common/` wins over any third-party
        # `common` that may sit in site-packages.
        sys.path.insert(0, repo_root)
    from common.testing.ac_evidence import record_ac_evidence

    def _emit(**kwargs):
        return record_ac_evidence(record_property, **kwargs)

    return _emit


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
    clear_fx_cache()
    yield
    clear_fx_cache()


@pytest.fixture(autouse=True)
def disable_external_market_data_fetch(monkeypatch):
    """Keep tests deterministic unless a test explicitly enables provider fetches."""
    monkeypatch.setattr(settings, "market_data_lazy_fetch_enabled", False, raising=False)


# --- Helper to ensure 127.0.0.1 consistency ---
def normalize_url(url: str | None) -> str | None:
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
    """Generate database URL specific to pytest-xdist worker with namespace isolation.

    Args:
        worker_id: Worker identifier ('master' for serial, 'gw0'/'gw1'/... for parallel)

    Returns:
        Database URL with namespace and worker-specific database name for parallel execution
    """
    # Get namespace from environment (set by test_lifecycle.py)
    namespace = os.environ.get("TEST_NAMESPACE", "default")

    # Build base database name with namespace
    base_db_name = f"finance_report_test_{namespace}"

    # Construct URL with namespace-aware database name
    base_url = (
        normalize_url(
            os.environ.get(
                "DATABASE_URL",
                f"postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/{base_db_name}",
            )
        )
        or f"postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/{base_db_name}"
    )

    if worker_id != "master":
        url_obj = make_url(base_url)
        assert url_obj.database is not None
        worker_suffix = f"_{worker_id}"
        max_base_len = 63 - len(worker_suffix)
        worker_db_name = f"{url_obj.database[:max_base_len]}{worker_suffix}"
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

# Set ENVIRONMENT for pydantic settings
os.environ["ENVIRONMENT"] = "testing"


# --- Structlog Configuration for Tests ---
@pytest.fixture(autouse=True, scope="session")
def configure_structlog_for_tests():
    """Configure structlog for proper capsys capture in tests."""
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

    yield

    structlog.reset_defaults()


async def ensure_database(db_url: str):
    """Ensure the test database exists.

    Args:
        db_url: Full database URL including worker-specific database name
    """
    url = make_url(db_url)
    db_name = url.database

    # Connect to 'postgres' database to check/create test db
    # Must run in AUTOCOMMIT mode to create database
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
        if isinstance(e, (SQLAlchemyError,)):
            logger.error(
                f"Test database setup failed: {type(e).__name__}: {e}",
                extra={"database": db_name, "error_type": type(e).__name__},
            )
        print(f"Warning: Failed to ensure database exists: {e}")
        if isinstance(e, SQLAlchemyError):
            raise RuntimeError(f"Cannot proceed without test database: {e}") from e
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def _schema_engine(test_database_url):
    """Build the test schema once per xdist worker and share one engine.

    Each xdist worker owns its own database (see get_test_db_url), so the schema
    only needs to be created a single time per worker rather than on every test.
    Per-test isolation is provided by db_engine, which truncates all tables.

    The engine keeps NullPool because pytest-asyncio runs each test in its own
    event loop (asyncio_default_test_loop_scope = "function") and asyncpg
    connections are bound to the loop that created them; NullPool guarantees no
    connection is reused across loops. Only the (expensive) schema build is moved
    to session scope — not connection pooling.
    """
    await ensure_database(test_database_url)

    from src.database import Base
    from src.models import (  # noqa: F401
        Account,
        AiFeedback,
        BankStatement,
        BankStatementTransaction,
        ChatMessage,
        ChatSession,
        ConsistencyCheck,
        FxRate,
        JournalAuditLog,
        JournalEntry,
        JournalLine,
        PingState,
        ReconciliationMatch,
        User,
    )

    engine = create_async_engine(
        test_database_url,  # Use worker-specific URL
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables once for this worker.
    async with engine.begin() as conn:
        # Ensure clean slate - drop all tables with CASCADE to handle foreign keys
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        await conn.run_sync(Base.metadata.create_all)

        # TODO(tech-debt): ~100 test files create data with user_id=uuid4()
        # instead of using the test_user fixture. Until those are migrated,
        # we MUST drop user_id FKs in the test schema to avoid
        # ForeignKeyViolationError.  Production models retain the CASCADE FKs.
        def _strip_user_fks(connection):
            from sqlalchemy import MetaData as _Meta

            meta = _Meta()
            meta.reflect(bind=connection)
            for tbl in meta.tables.values():
                for fk in tbl.foreign_key_constraints:
                    if fk.referred_table.name == "users":
                        connection.execute(text(f'ALTER TABLE "{tbl.name}" DROP CONSTRAINT "{fk.name}"'))

        await conn.run_sync(_strip_user_fks)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_engine(request, _schema_engine):
    """Provide the shared per-worker engine with a pristine database per test.

    The schema is built once by `_schema_engine`; here each test only truncates
    all tables (RESTART IDENTITY CASCADE) so it starts from an empty, pristine
    state with sequences reset. This replaces the previous per-test
    DROP SCHEMA + create_all + full reflect, which measured ~205ms/test versus
    ~49ms for truncate. No test performs its own schema DDL, so a data-only reset
    is equivalent to the old schema rebuild for isolation purposes.
    """
    if request.node.get_closest_marker("no_db"):
        yield None
        return

    from src.database import Base

    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with _schema_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

    yield _schema_engine


@pytest_asyncio.fixture(scope="function", autouse=True)
async def patch_database_connection(db_engine):
    """Ensure all tests use the test database connection via hook.

    This handles tests that manually instantiate the app/client without using
    the client fixture.
    """
    if db_engine is None:
        yield
        return

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
async def client(db_engine, test_user, test_database_url):
    """Create async test client with database initialized."""

    os.environ["DATABASE_URL"] = test_database_url

    # Database connection is handled by patch_database_connection autouse fixture

    # Import app after setting env var
    from src.main import app
    from src.security import create_access_token

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
        pass


@pytest_asyncio.fixture(scope="function")
async def public_client(db_engine, test_database_url):
    """Create async test client without auth headers."""
    os.environ["DATABASE_URL"] = test_database_url

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
