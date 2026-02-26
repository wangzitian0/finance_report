"""FX Revaluation Service - Infrastructure for unrealized FX gain/loss tracking.

This service provides the foundation for:
1. Calculating unrealized FX gains/losses on foreign currency balances
2. Creating revaluation journal entries at period-end
3. Distinguishing realized vs unrealized FX impacts in reporting
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.config import settings
from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.fx import FxRateError, get_exchange_rate

logger = get_logger(__name__)

REVALUATION_ACCOUNT_TYPES = (AccountType.ASSET, AccountType.LIABILITY)


class RevaluationError(Exception):
    pass


@dataclass
class AccountRevaluation:
    account_id: UUID
    account_name: str
    account_currency: str
    original_balance: Decimal
    original_balance_base: Decimal
    revalued_balance_base: Decimal
    unrealized_gain_loss: Decimal
    fx_rate_used: Decimal


@dataclass
class RevaluationResult:
    revaluation_date: date
    base_currency: str
    accounts_revalued: list[AccountRevaluation]
    total_unrealized_gain_loss: Decimal
    journal_entry_id: UUID | None


async def get_foreign_currency_accounts(
    db: AsyncSession,
    user_id: UUID,
) -> list[Account]:
    """Get all asset/liability accounts with non-base currency."""
    base_currency = settings.base_currency.upper()

    stmt = (
        select(Account)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(REVALUATION_ACCOUNT_TYPES))
        .where(Account.currency != base_currency)
        .where(Account.is_active == True)  # noqa: E712
    )

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def calculate_account_balance_in_currency(
    db: AsyncSession,
    account: Account,
) -> Decimal:
    """Calculate account balance in its native currency (nominal amount)."""
    from src.services.accounting import calculate_account_balance

    return await calculate_account_balance(db, account.id, account.user_id)


async def calculate_account_historical_cost(
    db: AsyncSession,
    account: Account,
) -> Decimal:
    """
    Calculate account balance in base currency using historical FX rates.

    Sums (line.amount * line.fx_rate) for all posted/reconciled entries.
    If fx_rate is None, assumes 1.0 (base currency).
    """
    debit_query = (
        select(
            func.coalesce(
                func.sum(JournalLine.amount * func.coalesce(JournalLine.fx_rate, Decimal("1.0"))),
                Decimal("0"),
            )
        )
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account.id)
        .where(JournalLine.direction == Direction.DEBIT)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    credit_query = (
        select(
            func.coalesce(
                func.sum(JournalLine.amount * func.coalesce(JournalLine.fx_rate, Decimal("1.0"))),
                Decimal("0"),
            )
        )
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account.id)
        .where(JournalLine.direction == Direction.CREDIT)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    debit_result = await db.execute(debit_query)
    credit_result = await db.execute(credit_query)

    total_debit = debit_result.scalar() or Decimal("0")
    total_credit = credit_result.scalar() or Decimal("0")

    net_balance = total_debit - total_credit

    if account.type in (AccountType.ASSET, AccountType.EXPENSE):
        return net_balance
    else:
        return -net_balance


async def calculate_unrealized_fx_for_account(
    db: AsyncSession,
    account: Account,
    revaluation_date: date,
    base_currency: str,
) -> AccountRevaluation | None:
    """Calculate unrealized FX gain/loss for a single account.

    Compares the account's balance at historical cost (recorded FX rates)
    vs current spot rate to determine unrealized gain/loss.
    """
    balance = await calculate_account_balance_in_currency(db, account)

    if balance == Decimal("0"):
        return None

    try:
        current_rate = await get_exchange_rate(
            db,
            base_currency=account.currency,
            quote_currency=base_currency,
            rate_date=revaluation_date,
        )
    except FxRateError as e:
        raise RevaluationError(
            f"Missing FX rate for {account.currency}/{base_currency} on {revaluation_date}: {e}"
        ) from e

    revalued_base = balance * current_rate

    # Calculate historical cost basis from actual transactions
    original_base = await calculate_account_historical_cost(db, account)

    unrealized = revalued_base - original_base

    return AccountRevaluation(
        account_id=account.id,
        account_name=account.name,
        account_currency=account.currency,
        original_balance=balance,
        original_balance_base=original_base,
        revalued_balance_base=revalued_base,
        unrealized_gain_loss=unrealized,
        fx_rate_used=current_rate,
    )


async def calculate_unrealized_fx_gains(
    db: AsyncSession,
    user_id: UUID,
    revaluation_date: date,
) -> RevaluationResult:
    """Calculate unrealized FX gains/losses for all foreign currency accounts.

    This is the main entry point for period-end FX revaluation calculation.
    It does NOT create journal entries - use create_revaluation_entry for that.
    """
    base_currency = settings.base_currency.upper()
    accounts = await get_foreign_currency_accounts(db, user_id)

    revaluations: list[AccountRevaluation] = []
    total_unrealized = Decimal("0")

    for account in accounts:
        reval = await calculate_unrealized_fx_for_account(db, account, revaluation_date, base_currency)
        if reval is not None:
            revaluations.append(reval)
            total_unrealized += reval.unrealized_gain_loss

    logger.info(
        "Calculated unrealized FX gains/losses",
        user_id=str(user_id),
        revaluation_date=revaluation_date.isoformat(),
        accounts_count=len(revaluations),
        total_unrealized=str(total_unrealized),
    )

    return RevaluationResult(
        revaluation_date=revaluation_date,
        base_currency=base_currency,
        accounts_revalued=revaluations,
        total_unrealized_gain_loss=total_unrealized,
        journal_entry_id=None,
    )


async def get_or_create_fx_gain_loss_account(
    db: AsyncSession,
    user_id: UUID,
) -> Account:
    """Get or create the system account for unrealized FX gains/losses.

    This account is used to book revaluation entries. It's an Equity account
    that represents Other Comprehensive Income (OCI) for FX revaluation.
    """
    fx_account_name = "Unrealized FX Gain/Loss"
    fx_account_code = "SYS-FX-REVAL"

    stmt = select(Account).where(Account.user_id == user_id).where(Account.code == fx_account_code)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        return existing

    new_account = Account(
        user_id=user_id,
        name=fx_account_name,
        code=fx_account_code,
        type=AccountType.EQUITY,
        currency=settings.base_currency.upper(),
        is_active=True,
        description="System account for unrealized FX gains and losses from currency revaluation",
    )
    db.add(new_account)
    try:
        await db.flush()
    except SQLAlchemyError as e:
        raise RevaluationError(f"Failed to create FX gain/loss account: {e}") from e

    logger.info(
        "Created FX gain/loss account",
        user_id=str(user_id),
        account_id=str(new_account.id),
    )

    return new_account


async def create_revaluation_entry(
    db: AsyncSession,
    user_id: UUID,
    revaluation_date: date,
    revaluations: list[AccountRevaluation],
    fx_account: Account,
    auto_post: bool = False,
) -> JournalEntry | None:
    """Create a journal entry to record unrealized FX gains/losses.

    Creates balanced double-entry:
    - Debit/Credit each foreign currency account for the revaluation adjustment
    - Offsetting entry to the FX Gain/Loss equity account
    """
    material_revaluations = [r for r in revaluations if abs(r.unrealized_gain_loss) >= Decimal("0.01")]

    if not material_revaluations:
        logger.info(
            "No material FX revaluation needed",
            revaluation_date=revaluation_date.isoformat(),
        )
        return None

    total_adjustment = sum(r.unrealized_gain_loss for r in material_revaluations)

    entry = JournalEntry(
        user_id=user_id,
        entry_date=revaluation_date,
        memo=f"FX Revaluation - {revaluation_date.isoformat()}",
        source_type=JournalEntrySourceType.FX_REVALUATION,
        status=JournalEntryStatus.POSTED if auto_post else JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    base_currency = settings.base_currency.upper()

    for reval in material_revaluations:
        # FX Gain: Asset worth MORE in base currency → DEBIT asset, CREDIT FX account
        # FX Loss: Asset worth LESS in base currency → CREDIT asset, DEBIT FX account
        if reval.unrealized_gain_loss > 0:
            asset_direction = Direction.DEBIT
        else:
            asset_direction = Direction.CREDIT

        asset_line = JournalLine(
            journal_entry_id=entry.id,
            account_id=reval.account_id,
            direction=asset_direction,
            amount=abs(reval.unrealized_gain_loss),
            currency=base_currency,
            fx_rate=Decimal("1"),
            event_type="fx_revaluation",
            tags={"revaluation_date": revaluation_date.isoformat()},
        )
        db.add(asset_line)

    # Offsetting entry: opposite direction to net asset adjustments
    if total_adjustment > 0:
        fx_direction = Direction.CREDIT
    else:
        fx_direction = Direction.DEBIT

    fx_line = JournalLine(
        journal_entry_id=entry.id,
        account_id=fx_account.id,
        direction=fx_direction,
        amount=abs(total_adjustment),
        currency=base_currency,
        fx_rate=Decimal("1"),
        event_type="fx_revaluation",
        tags={"revaluation_date": revaluation_date.isoformat()},
    )
    db.add(fx_line)

    await db.flush()
    await db.refresh(entry, ["lines"])

    total_debits = sum(line.amount for line in entry.lines if line.direction == Direction.DEBIT)
    total_credits = sum(line.amount for line in entry.lines if line.direction == Direction.CREDIT)

    if abs(total_debits - total_credits) >= Decimal("0.01"):
        raise RevaluationError(f"Revaluation entry is unbalanced: debits={total_debits}, credits={total_credits}")

    return entry


async def run_period_end_revaluation(
    db: AsyncSession,
    user_id: UUID,
    revaluation_date: date,
    auto_post: bool = False,
) -> RevaluationResult:
    """Run full period-end FX revaluation process.

    This is the main entry point for period-end processing:
    1. Calculate unrealized gains/losses for all foreign currency accounts
    2. Create/get the FX Gain/Loss equity account
    3. Create a journal entry to record the revaluation

    Returns the revaluation result with journal entry ID if created.
    """
    result = await calculate_unrealized_fx_gains(db, user_id, revaluation_date)

    if not result.accounts_revalued:
        logger.info(
            "No foreign currency accounts to revalue",
            user_id=str(user_id),
            revaluation_date=revaluation_date.isoformat(),
        )
        return result

    fx_account = await get_or_create_fx_gain_loss_account(db, user_id)

    entry = await create_revaluation_entry(
        db=db,
        user_id=user_id,
        revaluation_date=revaluation_date,
        revaluations=result.accounts_revalued,
        fx_account=fx_account,
        auto_post=auto_post,
    )

    if entry:
        result.journal_entry_id = entry.id

    return result


def is_revaluation_entry(entry: JournalEntry) -> bool:
    """Check if a journal entry is an FX revaluation entry."""
    return entry.source_type == JournalEntrySourceType.FX_REVALUATION


def get_revaluation_entries_filter():
    """SQLAlchemy filter clause for revaluation entries."""
    return JournalEntry.source_type == JournalEntrySourceType.FX_REVALUATION
