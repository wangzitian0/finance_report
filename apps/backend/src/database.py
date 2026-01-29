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


def set_test_session_maker(maker: async_sessionmaker[AsyncSession] | None) -> None:
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
        # For SQLAlchemy 2.0, check pool to get underlying engine
        pool = getattr(bind, "pool", None)
        if pool:
            async_engine = pool._creator
        else:
            async_engine = getattr(bind, "sync_engine", None)
    elif isinstance(bind, Engine):
        async_engine = bind
    else:
        async_engine = getattr(bind, "sync_engine", None)

    if not isinstance(async_engine, AsyncEngine):
        raise RuntimeError("Async engine unavailable for session maker creation")

    return async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for database session.

    Creates a test session maker if _test_session_maker is set, ensuring test
    DATABASE_URL is used instead of the production database_url.
    """
    global _test_session_maker
    if _test_session_maker:
        # Create a new session maker from test session's bind to get correct engine
        from sqlalchemy.engine.url import make_url
        from src.config import settings

        # Read DATABASE_URL from environment (set by client fixture)
        test_url = make_url(settings.database_url)
        engine = create_async_engine(test_url, echo=False, pool_pre_ping=True)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    else:
        maker = async_session_maker

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
