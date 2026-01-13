"""Tests for core database module."""

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db, init_db, Base, async_session_maker


def test_database_base_exists():
    """Test that Base is properly defined."""
    assert Base is not None
    assert hasattr(Base, "metadata")


def test_async_session_maker_exists():
    """Test that async_session_maker is configured."""
    assert async_session_maker is not None


@pytest.mark.asyncio
async def test_get_db_context_manager():
    """Test that get_db works as a context manager."""
    context = get_db()

    # Test that it returns a context manager
    assert hasattr(context, "__aenter__")
    assert hasattr(context, "__aexit__")


@pytest.mark.asyncio
@patch("src.core.database.engine")
async def test_init_db(mock_engine):
    """Test database initialization."""
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    with patch("src.core.database.Base") as mock_base:
        await init_db()

        mock_engine.begin.assert_called_once()
        mock_conn.run_sync.assert_called_once_with(mock_base.metadata.create_all)


def test_database_configuration():
    """Test database engine configuration."""
    from src.core.database import engine

    # Test that engine is configured
    assert engine is not None
