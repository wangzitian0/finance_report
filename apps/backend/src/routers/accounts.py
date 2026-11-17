"""Account management API router."""

from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from src.composition import post_guided_opening_balances
from src.deps import Ctx, ReadCtx
from src.ledger import (
    AccountType,
    JournalLine,
    account_service,
    calculate_account_balance,
    calculate_account_balances,
    get_opening_balance_readiness,
)
from src.observability import get_logger
from src.platform import ValidationFailedError
from src.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountUpdate,
)
from src.schemas.account import OpeningBalanceReadinessResponse, OpeningBalanceRequest
from src.schemas.journal import JournalEntryResponse

router = APIRouter(prefix="/accounts", tags=["accounts"])
logger = get_logger(__name__)


@router.post("/opening-balances", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def post_opening_balances(
    payload: OpeningBalanceRequest,
    ctx: Ctx,
) -> JournalEntryResponse:
    """Guided opening-balance flow (#949): establish year-start account balances.

    Posts one balanced journal entry that increases each supplied account to its
    opening balance and offsets the net into the system Opening Balance Equity
    account, so a cross-year balance sheet is complete from the start.
    """
    db, user_id = ctx.db, ctx.user_id
    entry = await post_guided_opening_balances(
        db,
        user_id,
        entry_date=payload.entry_date,
        balances=payload.balances,
        currency=payload.currency,
        memo=payload.memo,
    )
    await db.flush()
    await db.refresh(entry, ["lines"])
    return JournalEntryResponse.model_validate(entry)


@router.get("/opening-balance-readiness", response_model=OpeningBalanceReadinessResponse)
async def get_opening_balance_readiness_status(
    ctx: ReadCtx,
) -> OpeningBalanceReadinessResponse:
    """Readiness nudge (#949): is the balance sheet at risk of being incomplete?

    Returns ``needs_opening_balance=True`` when the user has posted activity but no
    opening-balance entry on or before its earliest date, so the UI can warn before
    they ship a silently-incomplete balance sheet.
    """
    readiness = await get_opening_balance_readiness(ctx.db, ctx.user_id)
    return OpeningBalanceReadinessResponse.model_validate(readiness)


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    ctx: Ctx,
) -> AccountResponse:
    """Create a new account."""
    db, user_id = ctx.db, ctx.user_id
    account = await account_service.create_account(db, user_id, account_data)

    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    ctx: ReadCtx,
    account_type: AccountType | None = None,
    is_active: bool | None = None,
    include_balance: bool = Query(False, description="Include balance (slower)"),
    limit: int = Query(100, ge=1, le=500, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> AccountListResponse:
    """List all accounts with optional filters and pagination.

    Set include_balance=true to calculate balances (may be slower with many accounts).
    """
    db, user_id = ctx.db, ctx.user_id
    accounts, total = await account_service.list_accounts(
        db, user_id, account_type=account_type, is_active=is_active, limit=limit, offset=offset
    )

    balances = {}
    if include_balance:
        balances = await calculate_account_balances(db, accounts, user_id)

    items = []
    for account in accounts:
        response = AccountResponse.model_validate(account)
        if include_balance:
            response.balance = balances.get(account.id)
        items.append(response)

    return AccountListResponse(items=items, total=total)


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: UUID,
    account_data: AccountUpdate,
    ctx: Ctx,
) -> AccountResponse:
    """Update an account's mutable fields."""
    db, user_id = ctx.db, ctx.user_id
    account = await account_service.update_account(db, user_id, account_id, account_data)

    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: UUID,
    ctx: Ctx,
) -> None:
    """Delete an account by id."""
    db, user_id = ctx.db, ctx.user_id
    account = await account_service.get_account(db, user_id, account_id)

    if account.is_system:
        raise ValidationFailedError("System accounts cannot be modified or deleted")

    result = await db.execute(select(JournalLine).where(JournalLine.account_id == account_id).limit(1))
    if result.scalar_one_or_none():
        raise ValidationFailedError("Cannot delete account with existing transactions. Archive it instead.")

    await db.delete(account)
    await db.flush()
