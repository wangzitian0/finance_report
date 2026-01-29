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
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Test hook to override session maker
_test_session_maker = None


# Cache for test engine to avoid recreating it
_test_engine: AsyncEngine | None = None


def set_test_session_maker(maker: async_sessionmaker[AsyncSession] | None) -> None:
    """Set a test session maker to override the default one."""
    global _test_session_maker
    _test_session_maker = maker


def set_test_engine(engine: AsyncEngine) -> None:
    """Set a test engine for use in get_db()."""
    global _test_engine
    _test_engine = engine
    """Set a test session maker to override the default one."""
    global _test_session_maker
    _test_session_maker = maker


def create_session_maker_from_db(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Create a new session maker sharing the same engine as the provided session.

    This is essential for background tasks to get a fresh session using the same
    database bind, which is particularly important during tests where the session
    might be bound to a specific test transaction.
    """
    bind = db.bind or db.get_bind()
    if isinstance(bind, AsyncEngine):
        async_engine = bind
    else:
        # For test sessions, get engine from bind or module-level test engine
        async_engine = bind.sync_engine if isinstance(bind, Engine) else (_test_engine or engine)

    if not isinstance(async_engine, AsyncEngine):
        raise RuntimeError("Async engine unavailable for session maker creation")

    return async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for database session."""
    # Use test engine if set, otherwise fall back to default
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
