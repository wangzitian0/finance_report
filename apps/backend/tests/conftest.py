"""Test fixtures and configuration."""

import logging
import os
import sys
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

# Eagerly register every ORM model on Base.metadata at collection time so any
# test session — including isolated single-file or ``no_db`` runs — has all
# mappers configured (replaces the former ``from src.models import ...`` hub
# side effect; issue #1461).
import src.models._registry  # noqa: F401
from src.config import settings
from src.observability import get_logger
from src.reporting import register_fx_gateway, register_manual_valuation_lines_provider
from src.services.fx import (
    FxRateError,
    PrefetchedFxRates,
    clear_fx_cache,
    convert_amount,
    convert_money,
    get_average_rate,
    get_exchange_rate,
)
from src.services.reporting.manual_valuation import _build_manual_valuation_lines

# Wire reporting's composition-root ports for direct (no-app) test runs — the
# same registrations main.py performs at startup (#1666): the FX seam and the
# manual-valuation lines builder still live in the services/ remainder pending
# the pricing cutover (#1610), and reporting reaches them only by injection.
# Module-top so it precedes every test module import.
register_fx_gateway(
    get_exchange_rate=get_exchange_rate,
    get_average_rate=get_average_rate,
    convert_amount=convert_amount,
    convert_money=convert_money,
    prefetched_fx_rates=PrefetchedFxRates,
    fx_rate_error=FxRateError,
)
register_manual_valuation_lines_provider(_build_manual_valuation_lines)

# Make the repo's ``common/`` importable at collection time (not just inside the
# ``ac_evidence`` fixture). conftest.py is imported before the test modules in
# this tree, so a backend test can carry a top-level co-located proof decorator
# (``from common.testing.ac_proof import ac_proof``) without ImportError. Insert
# at the front so the repo's ``common/`` wins over any third-party ``common`` in
# site-packages. This only widens what is importable; tests that do not import
# ``common`` are unaffected.
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logger = get_logger(__name__)


# --- LLM cassette layer (transparent per-request decision, #1596/#1597) ---
# The HARNESS engages the layer exactly once; individual tests never know (and
# never say) whether a response is real or frozen. Per request, inside the layer:
# HIT serves the frozen response; a MISS is a hard failure in CI (never a skip or
# a silent network call) and auto-records locally when a provider key exists.
# ``--llm-record`` (``make llm-record``) maps to the layer-owned refresh knob so
# an operator can re-record existing cassettes; refresh is refused in CI.
def pytest_addoption(parser):
    parser.addoption(
        "--llm-record",
        action="store_true",
        default=False,
        help="Re-record LLM cassettes (layer refresh knob; real provider call + write cassette).",
    )


def pytest_configure(config):
    os.environ.setdefault("LLM_CASSETTE_ENGAGE", "1")
    if config.getoption("--llm-record"):
        os.environ["LLM_CASSETTE_REFRESH"] = "1"


def pytest_sessionfinish(session, exitstatus):
    """Dump the cassettes this process served (orphan-gate substrate, #1597).

    xdist workers each run this hook in their own process; each writes its OWN
    ``served-cassettes-<pid>.txt`` (no shared-file appends to interleave) under
    a path anchored to this file (no CWD assumption). CI merges the shard
    artifacts in the finish job and fails on any committed cassette no job
    ever served.
    """
    from src.llm.extension.cassette import session_served_keys

    served = session_served_keys()
    if not served:
        return
    out = Path(__file__).resolve().parents[1] / "test-results"
    out.mkdir(exist_ok=True)
    (out / f"served-cassettes-{os.getpid()}.txt").write_text(
        "".join(f"{k}\n" for k in sorted(served)), encoding="utf-8"
    )


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
# Prevent Bootloader dependency checks from making real network/engine calls.
# Covers BOTH checks symmetrically: _check_database (its own engine causes event
# loop conflicts) and _check_s3 (uses aioboto3 — without a stub it hits a dead S3
# endpoint and burns ~8s on connect-timeout+retries per /health call, the real
# cost behind the slow /health tests). Tests that assert specific S3/DB health
# behaviour monkeypatch these again, which overrides the defaults set here.
@pytest.fixture(autouse=True)
def mock_bootloader_checks():
    """Stub Bootloader dependency checks (DB + S3) so /health is fast by default."""
    from src.boot import ServiceStatus

    async def ok_database():
        return ServiceStatus("database", "ok", "Mocked for tests", 0.0)

    async def ok_s3():
        return ServiceStatus("s3", "ok", "Mocked for tests", 0.0)

    with (
        patch("src.boot.Bootloader._check_database", new=ok_database),
        patch("src.boot.Bootloader._check_s3", new=ok_s3),
    ):
        yield


# --- FX Cache Cleanup ---
@pytest.fixture(autouse=True)
def cleanup_fx_cache():
    """Clear FX cache before and after each test to ensure isolation."""
    clear_fx_cache()
    yield
    clear_fx_cache()


# --- Rate-limiter isolation (#410) ---
@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Drop in-memory rate-limiter state before/after each test.

    The limiters are process-global singletons keyed by client IP; without this
    the per-IP counters accumulate across the whole session and trip a 429
    cascade once the global API limit is exceeded (tests share one client IP).
    """
    from src.identity import auth_rate_limiter, register_rate_limiter
    from src.main import api_rate_limiter

    for limiter in (api_rate_limiter, auth_rate_limiter, register_rate_limiter):
        limiter.clear()
    yield
    for limiter in (api_rate_limiter, auth_rate_limiter, register_rate_limiter):
        limiter.clear()


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
        if isinstance(e, SQLAlchemyError):
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

    # Register every ORM table on Base.metadata before create_all so each
    # per-worker schema is complete regardless of which test module imported
    # what first. ``src.models._registry`` eagerly imports all model modules
    # (replacing the former ``from src.models import ...`` hub side effect); the
    # role packages (counter_tally + the shared outbox) live outside that
    # package, so they are imported explicitly here.
    import src.counter.extension.sql  # noqa: F401
    import src.identity.extension.sql  # noqa: F401  -- User/AiFeedback
    import src.models._registry  # noqa: F401
    import src.platform.extension.sql  # noqa: F401
    from src.database import Base

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
        # The test schema keeps the production CASCADE FKs to ``users`` (#991): tests
        # own their rows via the ``test_user`` fixture, so cross-user / cross-version
        # isolation leaks surface here instead of being silently allowed.

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
    from src.identity import User

    user = User(
        email=f"test-{uuid4()}@example.com",
        hashed_password="hashed",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_user_id(test_user):
    """Test user ID — a real persisted users row so production FKs resolve (#991).

    Shared single definition (EPIC-025 / #1158); previously re-declared
    identically in every accounting/reporting test module.
    """
    return test_user.id


@pytest_asyncio.fixture(scope="function")
async def client(db_engine, test_user, test_database_url):
    """Create async test client with database initialized."""

    os.environ["DATABASE_URL"] = test_database_url

    # Database connection is handled by patch_database_connection autouse fixture

    # Import app after setting env var
    from src.identity import create_access_token
    from src.main import app

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
