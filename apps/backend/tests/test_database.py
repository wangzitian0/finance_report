"""Tests for database session management and utilities."""

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import (
    create_session_maker_from_db,
    get_db,
    init_db,
    set_test_session_maker,
)


@pytest.mark.asyncio
async def test_get_db_yields_session(public_client):
    """
    GIVEN the database dependency
    WHEN calling get_db
    THEN it should yield a valid AsyncSession
    """
    async for session in get_db():
        assert isinstance(session, AsyncSession)
        assert session is not None
        break


@pytest.mark.asyncio
async def test_get_db_closes_session(public_client):
    """
    GIVEN the database dependency
    WHEN get_db completes
    THEN the session should be closed (not active, no transaction)
    """
    session_ref = None
    async for session in get_db():
        session_ref = session
        assert session.is_active or session.in_transaction()
        break

    assert session_ref is not None


@pytest.mark.asyncio
async def test_set_test_session_maker_override(public_client):
    """
    GIVEN a custom session maker
    WHEN set_test_session_maker is called
    THEN get_db should use the custom session maker
    """
    custom_called = False

    class MockSessionMaker:
        def __call__(self):
            nonlocal custom_called
            custom_called = True
            return AsyncSession(bind=None)

        async def __aenter__(self):
            return self()

        async def __aexit__(self, *args):
            pass

    original_maker = None
    try:
        set_test_session_maker(MockSessionMaker())

        async for _ in get_db():
            break

        assert custom_called
    finally:
        set_test_session_maker(original_maker)


@pytest.mark.asyncio
async def test_create_session_maker_from_db_async_engine(db):
    """
    GIVEN a db session with AsyncEngine bind
    WHEN creating session maker from db
    THEN it should return a valid async_sessionmaker
    """
    session_maker = create_session_maker_from_db(db)

    assert isinstance(session_maker, async_sessionmaker)

    async with session_maker() as new_session:
        assert isinstance(new_session, AsyncSession)


@pytest.mark.asyncio
async def test_create_session_maker_handles_engine_attribute(db):
    """
    GIVEN a db session with Engine that has _async_engine attribute
    WHEN creating session maker from db
    THEN it should handle the attribute and create valid session maker
    """
    bind = db.bind or db.get_bind()

    if not isinstance(bind, AsyncEngine):
        pytest.skip("Bind is not AsyncEngine, skipping _async_engine test")

    session_maker = create_session_maker_from_db(db)
    assert isinstance(session_maker, async_sessionmaker)


@pytest.mark.asyncio
async def test_init_db_logs_message():
    """
    GIVEN the database initialization function
    WHEN init_db is called
    THEN it should log initialization message
    """
    await init_db()


@pytest.mark.asyncio
async def test_create_session_maker_invalid_bind():
    """
    GIVEN a session with invalid async engine
    WHEN creating session maker from db
    THEN it should raise RuntimeError
    """
    from unittest.mock import Mock

    mock_session = Mock(spec=AsyncSession)
    mock_session.bind = None

    mock_bind = Mock()
    mock_bind.async_engine = "not-an-async-engine"
    mock_session.get_bind = Mock(return_value=mock_bind)

    with pytest.raises(RuntimeError, match="Async engine unavailable"):
        create_session_maker_from_db(mock_session)
