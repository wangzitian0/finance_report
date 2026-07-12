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
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit import JournalEntrySourceType
from src.audit.money import Money
from src.ledger import Entry, Leg
from src.ledger.orm.account import Account, AccountType
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.observability import get_logger
from src.services.fx import FxRateError, get_exchange_rate

logger = get_logger(__name__)
settings = src.config.settings

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
    as_of_date: date | None = None,
) -> Decimal:
    """Calculate account balance in its native currency.

    Posted FX revaluation entries are base-currency adjustments and must not
    change the nominal foreign-currency balance.
    """
    stmt = (
        select(
            JournalLine.direction,
            func.coalesce(func.sum(JournalLine.amount), Decimal("0")).label("total"),
        )
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == account.id)
        .where(JournalLine.currency == account.currency)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.source_type != JournalEntrySourceType.FX_REVALUATION)
        .group_by(JournalLine.direction)
    )
    if as_of_date is not None:
        stmt = stmt.where(JournalEntry.entry_date <= as_of_date)

    result = await db.execute(stmt)
    debit_total = Decimal("0")
    credit_total = Decimal("0")
    for row in result.all():
        amount = Decimal(str(row.total))
        if row.direction == Direction.DEBIT:
            debit_total += amount
        else:
            credit_total += amount

    if account.type in (AccountType.ASSET, AccountType.EXPENSE):
        return debit_total - credit_total
    return credit_total - debit_total


async def calculate_account_historical_cost(
    db: AsyncSession,
    account: Account,
    as_of_date: date,
) -> Decimal:
    """
    Calculate account balance in base currency using historical FX rates.

    Uses the line's recorded FX rate when present. When older journal lines do
    not store an explicit rate, falls back to the exchange rate as of the entry
    date. Posted FX revaluation entries are excluded because they are valuation
    adjustments, not historical cost.
    """
    stmt = (
        select(
            JournalLine.direction,
            JournalLine.amount,
            JournalLine.fx_rate,
            JournalEntry.entry_date,
        )
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account.id)
        .where(JournalLine.currency == account.currency)
        .where(JournalEntry.entry_date <= as_of_date)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.source_type != JournalEntrySourceType.FX_REVALUATION)
    )

    result = await db.execute(stmt)
    base_currency = settings.base_currency.upper()
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for row in result.all():
        if row.fx_rate is None:
            try:
                rate = await get_exchange_rate(db, account.currency, base_currency, row.entry_date)
            except FxRateError:
                logger.warning(
                    "Historical FX rate missing for revaluation cost basis, falling back to revaluation-date rate",
                    account_id=str(account.id),
                    currency=account.currency,
                    entry_date=row.entry_date.isoformat(),
                    revaluation_date=as_of_date.isoformat(),
                )
                rate = await get_exchange_rate(db, account.currency, base_currency, as_of_date)
        else:
            rate = Decimal(str(row.fx_rate))
        converted = Decimal(str(row.amount)) * rate
        if row.direction == Direction.DEBIT:
            total_debit += converted
        else:
            total_credit += converted

    net_balance = total_debit - total_credit

    if account.type in (AccountType.ASSET, AccountType.EXPENSE):
        return net_balance
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
    balance = await calculate_account_balance_in_currency(db, account, revaluation_date)

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
    original_base = await calculate_account_historical_cost(db, account, revaluation_date)

    if account.type == AccountType.LIABILITY:
        unrealized = original_base - revalued_base
    else:
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

    logger.debug(
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

    base_currency = settings.base_currency.upper()
    reval_tags = {"revaluation_date": revaluation_date.isoformat()}

    # Quantize each adjustment to the money quantum (2dp) up front so the Entry
    # balance is validated against exactly what the DECIMAL(18,2) columns persist.
    # Individual revaluations are material (>= 0.01), but their *sum* can be
    # sub-cent (e.g. +0.014 - 0.011 = 0.003) and would otherwise round to a
    # zero/unbalanced offset line at the DB layer.
    adjustments = [
        (reval.account_id, Money(reval.unrealized_gain_loss, base_currency).quantize())
        for reval in material_revaluations
    ]
    net = Money.sum([adj for _, adj in adjustments], currency=base_currency)

    # Build the legs first so the double-entry balance is guaranteed as a TYPE
    # before anything is persisted (Axiom D / double-entry integrity). This path
    # previously wrote raw JournalLines with no balance check at all.
    legs: list[Leg] = [
        # FX Gain: asset worth MORE in base currency → DEBIT asset; FX Loss → CREDIT.
        Leg(
            account_id,
            Direction.DEBIT if adj.is_positive() else Direction.CREDIT,
            abs(adj),
            Decimal("1"),
            "fx_revaluation",
            reval_tags,
        )
        for account_id, adj in adjustments
        if not adj.is_zero()
    ]

    # Offsetting FX leg, opposite to the net asset adjustment. When the net is zero
    # the asset legs already balance, so no offset line is added (which also avoids
    # the previously-possible zero-amount line).
    if not net.is_zero():
        legs.append(
            Leg(
                fx_account.id,
                Direction.CREDIT if net.is_positive() else Direction.DEBIT,
                abs(net),
                Decimal("1"),
                "fx_revaluation",
                reval_tags,
            )
        )

    if len(legs) < 2:
        # Nothing material survives quantization to net a balanced entry.
        return None

    Entry.of(*legs)  # raises UnbalancedEntryError if the legs do not net to zero

    entry = JournalEntry(
        user_id=user_id,
        entry_date=revaluation_date,
        memo=f"FX Revaluation - {revaluation_date.isoformat()}",
        source_type=JournalEntrySourceType.FX_REVALUATION,
        status=JournalEntryStatus.POSTED if auto_post else JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    for leg in legs:
        db.add(
            JournalLine(
                journal_entry_id=entry.id,
                account_id=leg.account_id,
                direction=leg.direction,
                amount=leg.money.amount,
                currency=leg.money.currency.code,
                fx_rate=leg.fx_rate,
                event_type=leg.event_type,
                tags=leg.tags,
            )
        )

    await db.flush()
    await db.refresh(entry, ["lines"])

    # Revaluation lines are all in base currency; sum as Money (cross-currency would raise).
    total_debits = Money.sum(
        (line.money for line in entry.lines if line.direction == Direction.DEBIT),
        currency=settings.base_currency,
    )
    total_credits = Money.sum(
        (line.money for line in entry.lines if line.direction == Direction.CREDIT),
        currency=settings.base_currency,
    )

    if abs((total_debits - total_credits).amount) >= Decimal("0.01"):
        raise RevaluationError(
            f"Revaluation entry is unbalanced: debits={total_debits.amount}, credits={total_credits.amount}"
        )

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
