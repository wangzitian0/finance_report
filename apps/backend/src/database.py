"""Database configuration and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,  # Max persistent connections
    max_overflow=20,  # Additional transient connections under load
    pool_recycle=3600,  # Recycle connections after 1 hour
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Test hook to override session maker
_test_session_maker = None


def set_test_session_maker(
    maker: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession] | None:
    """Set test session maker and return the previous value.

    Args:
        maker: New session maker to use for tests, or None to clear

    Returns:
        Previous session maker value
    """
    global _test_session_maker
    previous = _test_session_maker
    _test_session_maker = maker
    return previous


def get_test_session_maker() -> async_sessionmaker[AsyncSession] | None:
    """Get current test session maker.

    Returns:
        Current test session maker, or None if not set
    """
    return _test_session_maker


def create_session_maker_from_db(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Create a new session maker sharing the same engine as the provided session.

    This is essential for background tasks to get a fresh session using the same
    database bind, which is particularly important during tests where the session
    might be bound to a specific test transaction.
    """
    bind = db.bind or db.get_bind()
    if isinstance(bind, AsyncEngine):
        async_engine = bind
    elif isinstance(bind, Engine) and getattr(bind, "_async_engine", None):
        async_engine = bind._async_engine
    else:
        async_engine = getattr(bind, "async_engine", None)

    if not isinstance(async_engine, AsyncEngine):
        if _test_session_maker is not None:
            # Test-only fallback: When background tasks spawn during tests and can't
            # extract engine from the transaction-bound test session, use the test
            # session maker that was set up by conftest fixtures. This ensures
            # background tasks access the same test database.
            # Production code never sets _test_session_maker, so this path is unused.
            return _test_session_maker
        raise RuntimeError("Async engine unavailable for session maker creation")

    return async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for database session."""
    maker = _test_session_maker or async_session_maker
    async with maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    Database initialization is handled by the container entrypoint
    via Alembic migrations. This ensures consistency across all
    environments and prevents schema-code mismatch.
    """
    from src.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Database initialized (schema managed by migrations)")
