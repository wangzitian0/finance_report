"""Account management service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType
from src.schemas.account import AccountCreate, AccountUpdate


class AccountServiceError(Exception):
    """Base exception for account service errors."""


class AccountNotFoundError(AccountServiceError):
    """Account not found error."""


async def create_account(db: AsyncSession, user_id: UUID, account_data: AccountCreate) -> Account:
    """
    Create a new account.

    Args:
        db: Database session
        user_id: User UUID
        account_data: Account creation data

    Returns:
        Created account
    """
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
    return account


async def list_accounts(
    db: AsyncSession,
    user_id: UUID,
    account_type: AccountType | None = None,
    is_active: bool | None = None,
) -> list[Account]:
    """
    List all accounts with optional filters.

    Args:
        db: Database session
        user_id: User UUID
        account_type: Optional filter by account type
        is_active: Optional filter by active status

    Returns:
        List of accounts
    """
    query = select(Account).where(Account.user_id == user_id)

    if account_type:
        query = query.where(Account.type == account_type)
    if is_active is not None:
        query = query.where(Account.is_active == is_active)

    query = query.order_by(Account.type, Account.name)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_account(db: AsyncSession, user_id: UUID, account_id: UUID) -> Account:
    """
    Get account details.

    Args:
        db: Database session
        user_id: User UUID
        account_id: Account UUID

    Returns:
        Account details

    Raises:
        AccountNotFoundError: If account not found
    """
    result = await db.execute(
        select(Account).where(Account.id == account_id).where(Account.user_id == user_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise AccountNotFoundError(f"Account {account_id} not found")

    return account


async def update_account(
    db: AsyncSession, user_id: UUID, account_id: UUID, account_data: AccountUpdate
) -> Account:
    """
    Update account details.

    Args:
        db: Database session
        user_id: User UUID
        account_id: Account UUID
        account_data: Update data

    Returns:
        Updated account

    Raises:
        AccountNotFoundError: If account not found

    Note:
        Uses `exclude_unset=True` to allow partial updates. Nullable fields
        can be cleared by explicitly setting them to `None` in the request.
    """
    account = await get_account(db, user_id, account_id)

    # Update fields if provided (including explicit None to clear nullable fields)
    update_data = account_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if hasattr(account, field):
            setattr(account, field, value)

    await db.commit()
    await db.refresh(account)

    return account
