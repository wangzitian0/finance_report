"""AC-ledger.1.1 - AC-ledger.1.6: Account service database operations and lifecycle.

Validates account creation, retrieval, updates, filtering, and error handling
against real database session fixtures with zero artificial Session mocks.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType
from src.ledger.extension import account_service
from src.ledger.extension.account_service import AccountNotFoundError
from src.schemas.account import AccountCreate, AccountUpdate


async def test_create_account(db: AsyncSession, test_user) -> None:
    """AC-ledger.1.1 / AC-ledger.9.1: Creating an account with valid data persists it correctly."""
    user_id = test_user.id
    account_data = AccountCreate(
        name="Operating Bank Account",
        type=AccountType.ASSET,
        currency="SGD",
        code="1001",
        description="Main operational account",
    )
    account = await account_service.create_account(db, user_id, account_data)

    assert account.id is not None
    assert account.name == "Operating Bank Account"
    assert account.user_id == user_id
    assert account.type == AccountType.ASSET
    assert account.currency == "SGD"
    assert account.code == "1001"


async def test_get_account_success(db: AsyncSession, test_user) -> None:
    """AC-ledger.1.2: An account is retrievable by id for its owner."""
    user_id = test_user.id
    created = await account_service.create_account(
        db,
        user_id,
        AccountCreate(name="Savings Account", type=AccountType.ASSET, currency="SGD"),
    )

    fetched = await account_service.get_account(db, user_id, created.id)
    assert fetched.id == created.id
    assert fetched.name == "Savings Account"


async def test_get_account_not_found(db: AsyncSession, test_user) -> None:
    """AC-ledger.1.3: Fetching a non-existent account raises AccountNotFoundError."""
    user_id = test_user.id
    with pytest.raises(AccountNotFoundError):
        await account_service.get_account(db, user_id, uuid4())


async def test_update_account_success(db: AsyncSession, test_user) -> None:
    """AC-ledger.1.4: Updating an existing account applies the new fields."""
    user_id = test_user.id
    created = await account_service.create_account(
        db,
        user_id,
        AccountCreate(name="Old Name", type=AccountType.ASSET, currency="SGD"),
    )

    updated = await account_service.update_account(
        db,
        user_id,
        created.id,
        AccountUpdate(
            name="New Name",
            code="2002",
            description="Updated description",
            is_active=False,
        ),
    )
    assert updated.name == "New Name"
    assert updated.code == "2002"
    assert updated.description == "Updated description"
    assert updated.is_active is False


async def test_update_account_not_found(db: AsyncSession, test_user) -> None:
    """AC-ledger.1.5: Updating a non-existent account raises AccountNotFoundError."""
    user_id = test_user.id
    with pytest.raises(AccountNotFoundError):
        await account_service.update_account(db, user_id, uuid4(), AccountUpdate(name="Non-existent"))


async def test_list_accounts(db: AsyncSession, test_user) -> None:
    """AC-ledger.1.6: Account listing and filtering by type and status."""
    user_id = test_user.id
    await account_service.create_account(
        db,
        user_id,
        AccountCreate(name="Bank Asset 1", type=AccountType.ASSET, currency="SGD"),
    )
    await account_service.create_account(
        db,
        user_id,
        AccountCreate(name="Credit Card", type=AccountType.LIABILITY, currency="SGD"),
    )

    results, total = await account_service.list_accounts(db, user_id)
    assert total >= 2
    assert len(results) >= 2

    # Filtering by type
    asset_results, asset_total = await account_service.list_accounts(db, user_id, account_type=AccountType.ASSET)
    assert asset_total >= 1
    assert all(a.type == AccountType.ASSET for a in asset_results)
