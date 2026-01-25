"""Account management API router."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import AccountType, JournalLine
from src.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountUpdate,
)
from src.services import (
    AccountNotFoundError,
    account_service,
    calculate_account_balance,
    calculate_account_balances,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])
logger = get_logger(__name__)


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> AccountResponse:
    """Create a new account."""
    account = await account_service.create_account(db, user_id, account_data)

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
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> AccountListResponse:
    """List all accounts with optional filters.

    Set include_balance=true to calculate balances (may be slower with many accounts).
    """
    accounts = await account_service.list_accounts(db, user_id, account_type=account_type, is_active=is_active)

    balances = {}
    if include_balance:
        balances = await calculate_account_balances(db, accounts, user_id)

    items = []
    for account in accounts:
        response = AccountResponse.model_validate(account)
        if include_balance:
            response.balance = balances.get(account.id)
        items.append(response)

    return AccountListResponse(items=items, total=len(items))


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> AccountResponse:
    """Get account details with current balance."""
    try:
        account = await account_service.get_account(db, user_id, account_id)
    except AccountNotFoundError as e:
        logger.debug("Account not found", account_id=str(account_id))
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
    db: DbSession,
    user_id: CurrentUserId,
) -> AccountResponse:
    """Update account details."""
    try:
        account = await account_service.update_account(db, user_id, account_id, account_data)
    except AccountNotFoundError as e:
        logger.debug("Account not found for update", account_id=str(account_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete an account (if unused)."""
    try:
        account = await account_service.get_account(db, user_id, account_id)
    except AccountNotFoundError as e:
        logger.debug("Account not found for deletion", account_id=str(account_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    result = await db.execute(select(JournalLine).where(JournalLine.account_id == account_id).limit(1))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete account with existing transactions. Archive it instead.",
        )

    await db.delete(account)
    await db.commit()
