"""Account management API router."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.models import AccountType
from src.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountUpdate,
)
from src.services import (
    AccountNotFoundError,
    calculate_account_balance,
    create_account,
    get_account,
    list_accounts,
    update_account,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> AccountResponse:
    """Create a new account."""
    account = await create_account(db, user_id, account_data)

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
    accounts = await list_accounts(
        db, user_id, account_type=account_type, is_active=is_active
    )

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
    try:
        account = await get_account(db, user_id, account_id)
    except AccountNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
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
    try:
        account = await update_account(
            db, user_id, account_id, account_data
        )
    except AccountNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response