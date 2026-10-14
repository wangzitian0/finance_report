"""Account management service."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency
from src.database import create_session_maker_from_db
from src.ledger.base.validators import ValidationError
from src.ledger.orm.account import Account, AccountType
from src.schemas.account import AccountCreate, AccountUpdate

#: Returns the account that a lookup names, or ``None``. It runs on the session that it gets.
AccountFinder = Callable[[AsyncSession], Awaitable[Account | None]]

_ACCOUNT_CREATION_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")


class AccountServiceError(Exception):
    """Base exception for account service errors."""


class AccountNotFoundError(AccountServiceError):
    """Account not found error."""


async def opening_balance_currencies(
    db: AsyncSession, user_id: UUID, account_ids: list[UUID], currency: str | None
) -> set[str]:
    """Validate the owned opening targets before requesting historical FX inputs."""
    rows = (
        (await db.execute(select(Account.currency).where(Account.id.in_(account_ids), Account.user_id == user_id)))
        .scalars()
        .all()
    )
    if len(rows) != len(account_ids):
        raise ValidationError("Unknown or non-owned account(s)")
    currencies = {Currency.of(code).code for code in rows}
    if currency and currencies - {Currency.of(currency).code}:
        raise ValidationError("Opening balance currency does not match the currency of account")
    return currencies


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


async def find_or_create_account(
    db: AsyncSession,
    *,
    user_id: UUID,
    find: AccountFinder,
    build: Callable[[], Account],
) -> Account:
    """Return the account that ``find`` names. When none exists, create it so that the creation commits at once.

    No unique index protects a default account or the Processing account. Several requests of one user can
    create the same account together, for example when a user uploads several statements at once. A second row
    breaks the balances of the account and the netting of the Processing account.

    The creation therefore runs in its own short transaction, under a lock that lasts a few milliseconds. The
    new row is visible to every request at once. No request waits for the long transaction of another request.
    A lock that lasted to the end of the caller's transaction would let two requests wait for each other (#2415).
    The account stays when the caller rolls back. An account without entries changes no balance.

    The own transaction cannot see a user row that the caller has not committed (the registration flow). Then
    the caller's session creates the account under the same lock, because nobody else knows that user yet.
    """
    account = await find(db)
    if account is not None:
        return account
    if await _ensure_in_own_transaction(db, user_id=user_id, find=find, build=build):
        account = await find(db)
        if account is not None:
            return account
    await db.execute(_ACCOUNT_CREATION_LOCK, {"key": f"account-creation:{user_id}"})
    account = await find(db)
    if account is None:
        account = build()
        db.add(account)
        await db.flush()
        await db.refresh(account)
    return account


async def _ensure_in_own_transaction(
    db: AsyncSession, *, user_id: UUID, find: AccountFinder, build: Callable[[], Account]
) -> bool:
    """Create the account in a transaction of its own. ``False`` means that the caller has to create it."""
    try:
        session_maker = create_session_maker_from_db(db)
    except RuntimeError:
        return False
    async with session_maker() as own, own.begin():
        user_is_visible = (
            await own.execute(text("SELECT 1 FROM users WHERE id = :user_id"), {"user_id": user_id})
        ).first() is not None
        if not user_is_visible:
            return False
        await own.execute(_ACCOUNT_CREATION_LOCK, {"key": f"account-creation:{user_id}"})
        if await find(own) is None:
            own.add(build())
            await own.flush()
        return True


async def get_or_create_opening_balance_equity_account(
    db: AsyncSession,
    user_id: UUID,
    currency: str,
) -> Account:
    """Get or create the Opening Balance Equity account for a user (#949).

    Guided opening balances offset into this system-managed equity account so a
    user's starting position is captured as a balanced journal entry and the
    accounting equation holds (Assets = Liabilities + Equity) from day one.
    """
    result = await db.execute(
        select(Account).where(
            Account.user_id == user_id,
            Account.is_system == True,  # noqa: E712
            Account.code == "3199",
        )
    )
    # Tolerant fetch: a rare duplicate (e.g. concurrent first-time creates without
    # a DB uniqueness constraint) must not break opening-balance posting.
    account = result.scalars().first()
    normalized_currency = Currency.of(currency).code
    if account and Currency.of(account.currency).code != normalized_currency:
        raise ValidationError(
            f"Opening Balance Equity account currency is {account.currency}; got base currency {normalized_currency}"
        )
    if not account:
        account = Account(
            user_id=user_id,
            name="Opening Balance Equity",
            code="3199",
            type=AccountType.EQUITY,
            currency=normalized_currency,
            is_system=True,
            description="System-managed equity account for year-start opening balance entries",
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
