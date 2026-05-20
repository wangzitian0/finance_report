"""Account management API router."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import AccountType, JournalLine
from src.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountUpdate,
    ProcessingPendingItem,
    ProcessingPendingListResponse,
    ProcessingSummaryResponse,
)
from src.services import (
    AccountNotFoundError,
    account_service,
    calculate_account_balance,
    calculate_account_balances,
)
from src.services.processing_account import (
    find_transfer_pairs,
    get_unpaired_transfers,
    list_processing_transfer_legs,
)
from src.utils import raise_bad_request, raise_not_found

router = APIRouter(prefix="/accounts", tags=["accounts"])
logger = get_logger(__name__)


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> AccountResponse:
    account = await account_service.create_account(db, user_id, account_data)
    await db.commit()

    balance = await calculate_account_balance(db, account.id, user_id)

    response = AccountResponse.model_validate(account)
    response.balance = balance
    return response


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    db: DbSession,
    user_id: CurrentUserId,
    account_type: AccountType | None = None,
    is_active: bool | None = None,
    include_balance: bool = Query(False, description="Include balance (slower)"),
    limit: int = Query(100, ge=1, le=500, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> AccountListResponse:
    """List all accounts with optional filters and pagination.

    Set include_balance=true to calculate balances (may be slower with many accounts).
    """
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


@router.get("/processing/summary", response_model=ProcessingSummaryResponse)
async def get_processing_summary(
    db: DbSession,
    user_id: CurrentUserId,
) -> ProcessingSummaryResponse:
    pairs = await find_transfer_pairs(db, user_id)
    paired_ids = {pair.out_entry.id for pair in pairs} | {pair.in_entry.id for pair in pairs}
    unpaired = [item for item in await get_unpaired_transfers(db, user_id) if item["entry_id"] not in paired_ids]
    pending_count = len(unpaired)
    debits = sum((item["amount"] for item in unpaired if item["direction"] == "OUT"), start=Decimal("0"))
    credits = sum((item["amount"] for item in unpaired if item["direction"] == "IN"), start=Decimal("0"))
    pending_total = abs(debits - credits).quantize(Decimal("0.01"))
    oldest_pending_date = min((item["date"] for item in unpaired), default=None)
    return ProcessingSummaryResponse(
        pending_count=pending_count,
        pending_total=pending_total,
        currency=settings.base_currency,
        oldest_pending_date=oldest_pending_date,
    )


@router.get("/processing/pending", response_model=ProcessingPendingListResponse)
async def list_processing_pending(
    db: DbSession,
    user_id: CurrentUserId,
) -> ProcessingPendingListResponse:
    pairs = await find_transfer_pairs(db, user_id)
    paired_ids = {pair.out_entry.id for pair in pairs} | {pair.in_entry.id for pair in pairs}
    legs = [leg for leg in await list_processing_transfer_legs(db, user_id) if leg["entry_id"] not in paired_ids]
    items = [ProcessingPendingItem(**leg) for leg in legs]
    return ProcessingPendingListResponse(items=items, total=len(items))


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> AccountResponse:
    try:
        account = await account_service.get_account(db, user_id, account_id)
    except AccountNotFoundError as e:
        logger.debug("Account not found", account_id=str(account_id))
        raise_not_found("Account", cause=e)

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
    try:
        account = await account_service.update_account(db, user_id, account_id, account_data)
        await db.commit()
    except AccountNotFoundError as e:
        logger.debug("Account not found for update", account_id=str(account_id))
        raise_not_found("Account", cause=e)

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
    try:
        account = await account_service.get_account(db, user_id, account_id)
    except AccountNotFoundError as e:
        logger.debug("Account not found for deletion", account_id=str(account_id))
        raise_not_found("Account", cause=e)

    result = await db.execute(select(JournalLine).where(JournalLine.account_id == account_id).limit(1))
    if result.scalar_one_or_none():
        raise_bad_request("Cannot delete account with existing transactions. Archive it instead.")

    await db.delete(account)
    await db.commit()
