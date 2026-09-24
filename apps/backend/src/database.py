"""Database configuration and session management."""

from collections.abc import AsyncGenerator
from typing import cast

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


# SQLite (used in tests) does not support pool_size / max_overflow arguments.
# Only pass them for PostgreSQL connections.
_pool_kwargs: dict = {"pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    _pool_kwargs["pool_size"] = settings.db_pool_size
    _pool_kwargs["max_overflow"] = settings.db_pool_max_overflow
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    **_pool_kwargs,
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
    async_engine: AsyncEngine | None
    if isinstance(bind, AsyncEngine):
        async_engine = bind
    else:
        async_engine = cast(
            AsyncEngine | None,
            getattr(bind, "_async_engine", None) or getattr(bind, "async_engine", None),
        )

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
    from src.observability import get_logger

    logger = get_logger(__name__)
    logger.info("Database initialized (schema managed by migrations)")


def split_postgresql_ddl(sql: str) -> tuple[str, ...]:
    """Split PostgreSQL DDL script by semicolon while respecting $$ dollar quotes."""
    statements: list[str] = []
    start = 0
    in_dollar_quote = False
    index = 0

    while index < len(sql):
        if sql.startswith("$$", index):
            in_dollar_quote = not in_dollar_quote
            index += 2
            continue

        if sql[index] == ";" and not in_dollar_quote:
            statement = sql[start : index + 1].strip()
            if statement:
                statements.append(statement)
            start = index + 1

        index += 1

    trailing = sql[start:].strip()
    if trailing:
        statements.append(trailing)
    return tuple(statements)
