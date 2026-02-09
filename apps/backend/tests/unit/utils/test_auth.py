import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4, UUID
from fastapi import HTTPException, status
from src.auth import get_current_user_id
from src.security import create_access_token

@pytest.mark.asyncio
async def test_get_current_user_id_success():
    """AC8.2.4: Verify successful user ID resolution from token."""
    user_id = uuid4()
    token = create_access_token({"sub": str(user_id)})
    
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user_id
    mock_db.execute.return_value = mock_result
    
    resolved_id = await get_current_user_id(token=token, db=mock_db)
    assert resolved_id == user_id
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_current_user_id_invalid_token():
    """AC8.2.4: Verify failure on invalid JWT token."""
    mock_db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(token="invalid", db=mock_db)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED

@pytest.mark.asyncio
async def test_get_current_user_id_missing_sub():
    """AC8.2.4: Verify failure on token missing subject."""
    token = create_access_token({"not_sub": "value"})
    mock_db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(token=token, db=mock_db)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "missing subject" in exc.value.detail.lower()

@pytest.mark.asyncio
async def test_get_current_user_id_malformed_uuid():
    """AC8.2.4: Verify failure on malformed user UUID in token."""
    token = create_access_token({"sub": "not-a-uuid"})
    mock_db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(token=token, db=mock_db)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid user id format" in exc.value.detail.lower()

@pytest.mark.asyncio
async def test_get_current_user_id_not_found():
    """AC8.2.4: Verify failure when user does not exist in DB."""
    user_id = uuid4()
    token = create_access_token({"sub": str(user_id)})
    
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result
    
    with pytest.raises(HTTPException) as exc:
        await get_current_user_id(token=token, db=mock_db)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "user not found" in exc.value.detail.lower()
