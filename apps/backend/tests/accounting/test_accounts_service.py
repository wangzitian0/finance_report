"""AC2.1: Account router direct function tests.

These tests cover account service layer operations from EPIC-002:
 AC2.1.1: Account creation with balance
 AC2.1.2: Account listing with/without balance
 AC2.1.3: Account filtering by type and status
 AC2.1.4: Account fetching by ID
 AC2.1.5: Account update (name, code, description, is_active)
 AC2.1.6: Error handling for non-existent accounts
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import AccountType
from src.routers.accounts import (
    create_account,
    get_account,
    list_accounts,
    update_account,
)
from src.schemas.account import AccountCreate, AccountUpdate


@pytest.mark.asyncio
async def test_account_router_direct(db: AsyncSession, test_user) -> None:
    user_id = test_user.id
    created = await create_account(
        AccountCreate(name="Cash", type=AccountType.ASSET, currency="SGD"),
        db,
        user_id=user_id,
    )
    assert created.balance is not None

    listed = await list_accounts(include_balance=False, limit=100, offset=0, db=db, user_id=user_id)
    assert listed.total >= 1

    listed_with_balance = await list_accounts(include_balance=True, limit=100, offset=0, db=db, user_id=user_id)
    assert listed_with_balance.items[0].balance is not None

    filtered = await list_accounts(
        account_type=AccountType.ASSET,
        is_active=True,
        limit=100,
        offset=0,
        db=db,
        user_id=user_id,
    )
    assert filtered.total >= 1

    fetched = await get_account(created.id, db, user_id=user_id)
    assert fetched.id == created.id

    updated = await update_account(
        created.id,
        AccountUpdate(
            name="Cash Updated",
            code="1001",
            description="Updated account",
            is_active=False,
        ),
        db,
        user_id=user_id,
    )
    assert updated.name == "Cash Updated"
    assert updated.is_active is False

    with pytest.raises(HTTPException):
        await get_account(uuid4(), db, user_id=user_id)

    with pytest.raises(HTTPException):
        await update_account(uuid4(), AccountUpdate(name="Missing"), db, user_id=user_id)
