"""Tests for core auth module."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from uuid import uuid4

from src.core.auth import get_current_user_id


@pytest.mark.asyncio
async def test_get_current_user_id_success():
    """Test successful user ID resolution."""
    test_user_id = str(uuid4())

    mock_db = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none.return_value = True
    mock_db.execute.return_value = mock_result

    with patch("src.core.auth.select") as mock_select:
        with patch("src.core.auth.User") as mock_user:
            await get_current_user_id(test_user_id, mock_db)

            mock_user.id.__eq__.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_user_id_missing_header():
    """Test failure when X-User-Id header is missing."""
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(None, mock_db)

    assert exc_info.value.status_code == 401
    assert "Missing X-User-Id header" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_current_user_id_invalid_uuid():
    """Test failure when X-User-Id is not a valid UUID."""
    mock_db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id("invalid-uuid", mock_db)

    assert exc_info.value.status_code == 401
    assert "Invalid X-User-Id format" in str(exc_info.value.detail)
