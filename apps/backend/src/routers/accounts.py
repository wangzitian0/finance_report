"""Account management API router."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.models import Account, AccountType
from src.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountUpdate,
)
from src.services import calculate_account_balance

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> AccountResponse:
    """Create a new account."""
    account = Account(
        user_id=user_id,
        name=account_data.name,
        code=account_data.code,
        type=account_data.type,
        currency=account_data.currency,
        parent_id=account_data.parent_id,
        description=account_data.description,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    # Calculate balance
    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    account_type: AccountType | None = None,
    is_active: bool | None = None,
    include_balance: bool = Query(False, description="Include balance (slower)"),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> AccountListResponse:
    """List all accounts with optional filters.

    Set include_balance=true to calculate balances (may be slower with many accounts).
    """
    query = select(Account).where(Account.user_id == user_id)

    if account_type:
        query = query.where(Account.type == account_type)
    if is_active is not None:
        query = query.where(Account.is_active == is_active)

    query = query.order_by(Account.type, Account.name)

    result = await db.execute(query)
    accounts = result.scalars().all()

    # Calculate balances only if requested
    items = []
    for account in accounts:
        response = AccountResponse.model_validate(account)
        if include_balance:
            response.balance = await calculate_account_balance(db, account.id, user_id)
        items.append(response)

    return AccountListResponse(items=items, total=len(items))


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> AccountResponse:
    """Get account details with current balance."""
    result = await db.execute(
        select(Account).where(Account.id == account_id).where(Account.user_id == user_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )

    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: UUID,
    account_data: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> AccountResponse:
    """Update account details."""
    result = await db.execute(
        select(Account).where(Account.id == account_id).where(Account.user_id == user_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )

    # Update fields if provided
    if account_data.name is not None:
        account.name = account_data.name
    if account_data.code is not None:
        account.code = account_data.code
    if account_data.description is not None:
        account.description = account_data.description
    if account_data.parent_id is not None:
        account.parent_id = account_data.parent_id
    if account_data.is_active is not None:
        account.is_active = account_data.is_active

    await db.commit()
    await db.refresh(account)

    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response
