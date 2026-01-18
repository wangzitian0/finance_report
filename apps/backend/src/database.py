"""Database configuration and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
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
        raise RuntimeError("Async engine unavailable for session maker creation")

    return async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for database session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
