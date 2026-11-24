"""Rows that a test commits through its own engine must not outlive the test (#3176)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.database import create_app_engine
from src.identity import User
from tests.conftest import _DIRTY_TABLES, _cleanup_dirty_tables


async def _count_users(engine, user_id) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id})).scalar_one()


@pytest.mark.parametrize("through", ["the engine of the test", "a second engine"])
async def test_AC_test_infra_3176_a_committed_row_is_cleaned_before_the_next_test(
    db_engine, test_database_url, through: str
) -> None:
    """The cleanup knows every table that a test wrote, whichever engine wrote it."""
    user_id = uuid4()
    second = create_app_engine(test_database_url, pool_size=1, max_overflow=0)
    writer = db_engine if through == "the engine of the test" else second
    try:
        async with async_sessionmaker(writer, expire_on_commit=False)() as session:
            session.add(User(id=user_id, email=f"tracking-{user_id}@example.com", hashed_password="hashed"))
            await session.commit()
        assert await _count_users(db_engine, user_id) == 1
        assert "users" in _DIRTY_TABLES

        await _cleanup_dirty_tables(db_engine)

        assert await _count_users(db_engine, user_id) == 0
    finally:
        await second.dispose()
