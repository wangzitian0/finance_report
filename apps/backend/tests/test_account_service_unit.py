"""Unit tests for account service."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType
from src.schemas.account import AccountCreate, AccountUpdate
from src.services import account_service
from src.services.account_service import AccountNotFoundError


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock(spec=AsyncSession)
    return db


@pytest.fixture
def user_id():
    """Create a random user ID."""
    return uuid4()


@pytest.mark.asyncio
async def test_create_account(mock_db, user_id):
    """Test creating an account."""
    account_data = AccountCreate(
        name="Test Bank",
        type=AccountType.ASSET,
        currency="USD",
        description="Main bank account",
    )

    account = await account_service.create_account(mock_db, user_id, account_data)

    assert account.name == "Test Bank"
    assert account.user_id == user_id
    assert account.type == AccountType.ASSET

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(account)


@pytest.mark.asyncio
async def test_get_account_success(mock_db, user_id):
    """Test getting an existing account."""
    account_id = uuid4()
    mock_account = Account(id=account_id, user_id=user_id, name="Test")

    # Mock db.execute result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_account
    mock_db.execute.return_value = mock_result

    result = await account_service.get_account(mock_db, user_id, account_id)

    assert result == mock_account
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_account_not_found(mock_db, user_id):
    """Test getting a non-existent account."""
    account_id = uuid4()

    # Mock db.execute result to return None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(AccountNotFoundError):
        await account_service.get_account(mock_db, user_id, account_id)


@pytest.mark.asyncio
async def test_update_account_success(mock_db, user_id):
    """Test updating an account with all fields."""
    account_id = uuid4()
    parent_id = uuid4()
    mock_account = Account(id=account_id, user_id=user_id, name="Old Name")

    # Mock db.execute result for get_account call inside update_account
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_account
    mock_db.execute.return_value = mock_result

    update_data = AccountUpdate(
        name="New Name", code="123", description="New Desc", parent_id=parent_id, is_active=False
    )

    result = await account_service.update_account(mock_db, user_id, account_id, update_data)

    assert result.name == "New Name"
    assert result.code == "123"
    assert result.description == "New Desc"
    assert result.parent_id == parent_id
    assert result.is_active is False

    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(mock_account)


@pytest.mark.asyncio
async def test_update_account_not_found(mock_db, user_id):
    """Test updating a non-existent account."""
    account_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    update_data = AccountUpdate(name="New Name")

    with pytest.raises(AccountNotFoundError):
        await account_service.update_account(mock_db, user_id, account_id, update_data)


@pytest.mark.asyncio
async def test_list_accounts(mock_db, user_id):
    """Test listing accounts."""
    mock_accounts = [
        Account(id=uuid4(), user_id=user_id, name="Acc 1"),
        Account(id=uuid4(), user_id=user_id, name="Acc 2"),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_accounts
    mock_db.execute.return_value = mock_result

    results = await account_service.list_accounts(mock_db, user_id)

    assert len(results) == 2
    assert results == mock_accounts


@pytest.mark.asyncio
async def test_list_accounts_with_filters(mock_db, user_id):
    """Test listing accounts with filters."""
    mock_accounts = [Account(id=uuid4(), user_id=user_id, name="Acc 1")]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_accounts
    mock_db.execute.return_value = mock_result

    results = await account_service.list_accounts(
        mock_db, user_id, account_type=AccountType.ASSET, is_active=True
    )

    assert len(results) == 1
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_update_account_clear_fields(mock_db, user_id):
    """Test clearing nullable fields by setting them to None."""
    account_id = uuid4()
    mock_account = Account(
        id=account_id,
        user_id=user_id,
        name="Old Name",
        code="123",
        description="Old Desc",
        parent_id=uuid4(),
    )

    # Mock db.execute result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_account
    mock_db.execute.return_value = mock_result

    # Explicitly set nullable fields to None
    update_data = AccountUpdate(name="New Name", code=None, description=None, parent_id=None)

    result = await account_service.update_account(mock_db, user_id, account_id, update_data)

    assert result.name == "New Name"
    assert result.code is None
    assert result.description is None
    assert result.parent_id is None

    mock_db.commit.assert_called_once()
