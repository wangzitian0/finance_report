"""Account management service."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.models import Account, AccountType
from src.schemas.account import AccountCreate, AccountUpdate


class AccountServiceError(Exception):
    """Base exception for account service errors."""


class AccountNotFoundError(AccountServiceError):
    """Account not found error."""


async def create_account(db: AsyncSession, user_id: UUID, account_data: AccountCreate) -> Account:
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
    await db.flush()
    await db.refresh(account)
    return account


async def get_or_create_processing_account(db: AsyncSession, user_id: UUID, currency: str = "SGD") -> Account:
    """Get or create the Processing virtual account for a user."""
    result = await db.execute(
        select(Account).where(
            Account.user_id == user_id,
            Account.is_system == True,  # noqa: E712
            Account.code == "1199",
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        # Create Processing account
        account = Account(
            user_id=user_id,
            name="Processing",
            code="1199",
            type=AccountType.ASSET,
            currency=currency,
            is_system=True,
            description="System-managed virtual account for tracking in-transit transfers",
        )
        db.add(account)
        await db.flush()
        await db.refresh(account)

    return account


async def list_accounts(
    db: AsyncSession,
    user_id: UUID,
    account_type: AccountType | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Account], int]:
    base_query = select(Account).where(Account.user_id == user_id)
    base_query = base_query.where(Account.is_system == False)  # noqa: E712
    # Hide system accounts from user-facing lists

    if account_type:
        base_query = base_query.where(Account.type == account_type)
    if is_active is not None:
        base_query = base_query.where(Account.is_active == is_active)

    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = base_query.order_by(Account.type, Account.name).limit(limit).offset(offset)
    result = await db.execute(query)
    accounts = list(result.scalars().all())

    return accounts, total


async def get_account(db: AsyncSession, user_id: UUID, account_id: UUID) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id).where(Account.user_id == user_id))
    account = result.scalar_one_or_none()

    if not account:
        raise AccountNotFoundError(f"Account {account_id} not found")

    return account


async def update_account(db: AsyncSession, user_id: UUID, account_id: UUID, account_data: AccountUpdate) -> Account:
    account = await get_account(db, user_id, account_id)
    update_data = account_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if hasattr(account, field):
            setattr(account, field, value)

    await db.flush()
    await db.refresh(account)

    return account
