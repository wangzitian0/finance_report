"""Account management API router."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

# Mock user_id for now (will be replaced with auth)
MOCK_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    db: AsyncSession = Depends(get_db),
) -> AccountResponse:
    """Create a new account."""
    account = Account(
        user_id=MOCK_USER_ID,
        name=account_data.name,
        code=account_data.code,
        type=account_data.type,
        currency=account_data.currency,
        description=account_data.description,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    # Calculate balance
    balance = await calculate_account_balance(db, account.id, MOCK_USER_ID)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    account_type: AccountType | None = None,
    is_active: bool | None = None,
    include_balance: bool = Query(False, description="Include balance (slower)"),
    db: AsyncSession = Depends(get_db),
) -> AccountListResponse:
    """List all accounts with optional filters.

    Set include_balance=true to calculate balances (may be slower with many accounts).
    """
    query = select(Account).where(Account.user_id == MOCK_USER_ID)

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
            response.balance = await calculate_account_balance(db, account.id, MOCK_USER_ID)
        items.append(response)

    return AccountListResponse(items=items, total=len(items))


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> AccountResponse:
    """Get account details with current balance."""
    result = await db.execute(
        select(Account)
        .where(Account.id == account_id)
        .where(Account.user_id == MOCK_USER_ID)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found",
        )

    balance = await calculate_account_balance(db, account.id, MOCK_USER_ID)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: UUID,
    account_data: AccountUpdate,
    db: AsyncSession = Depends(get_db),
) -> AccountResponse:
    """Update account details."""
    result = await db.execute(
        select(Account)
        .where(Account.id == account_id)
        .where(Account.user_id == MOCK_USER_ID)
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
    if account_data.is_active is not None:
        account.is_active = account_data.is_active

    await db.commit()
    await db.refresh(account)

    balance = await calculate_account_balance(db, account.id, MOCK_USER_ID)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response
