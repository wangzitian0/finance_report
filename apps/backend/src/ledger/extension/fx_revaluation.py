"""Unrealized FX gain/loss calculation for foreign-currency asset and liability accounts.

This module only reads. It compares each account's historical cost with its
spot-rate value and returns the difference to reporting. It books no journal
entry: reporting recomputes the value on every report (#2774).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.config_app import get_effective_base_currency
from src.ledger.orm.account import Account, AccountType
from src.ledger.orm.journal import (
    Direction,
    JournalEntry,
    JournalLine,
    active_journal_entry_filter,
)
from src.observability import get_logger
from src.pricing import PricingError, get_exchange_rate

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


async def get_foreign_currency_accounts(
    db: AsyncSession,
    user_id: UUID,
    base_currency: str | None = None,
) -> list[Account]:
    """Get all asset/liability accounts with non-base currency."""
    resolved_base = (base_currency or await get_effective_base_currency(db, user_id=user_id)).upper()

    stmt = (
        select(Account)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(REVALUATION_ACCOUNT_TYPES))
        .where(Account.currency != resolved_base)
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
        .where(active_journal_entry_filter(JournalEntry))
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
    base_currency: str | None = None,
) -> Decimal:
    """Calculate account balance in base currency using historical FX rates."""
    stmt = (
        select(
            JournalLine.direction,
            JournalLine.amount,
            JournalLine.fx_rate,
            JournalEntry.entry_date,
            JournalEntry.base_currency,
        )
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account.id)
        .where(JournalLine.currency == account.currency)
        .where(JournalEntry.entry_date <= as_of_date)
        .where(active_journal_entry_filter(JournalEntry))
        .where(JournalEntry.source_type != JournalEntrySourceType.FX_REVALUATION)
    )

    result = await db.execute(stmt)
    resolved_base = (base_currency or await get_effective_base_currency(db, user_id=account.user_id)).upper()
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for row in result.all():
        entry_base = (getattr(row, "base_currency", None) or resolved_base).upper()
        if row.fx_rate is not None and entry_base == resolved_base:
            rate = Decimal(str(row.fx_rate))
        else:
            try:
                rate = await get_exchange_rate(db, account.currency, resolved_base, row.entry_date)
            except PricingError:
                logger.warning(
                    "Historical FX rate missing for revaluation cost basis, falling back to revaluation-date rate",
                    account_id=str(account.id),
                    currency=account.currency,
                    entry_date=row.entry_date.isoformat(),
                    revaluation_date=as_of_date.isoformat(),
                )
                rate = await get_exchange_rate(db, account.currency, resolved_base, as_of_date)
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
    """Calculate unrealized FX gain/loss for a single account."""
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
    except PricingError as e:
        raise RevaluationError(
            f"Missing FX rate for {account.currency}/{base_currency} on {revaluation_date}: {e}"
        ) from e

    revalued_base = balance * current_rate
    original_base = await calculate_account_historical_cost(db, account, revaluation_date, base_currency)

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
    base_currency: str | None = None,
) -> RevaluationResult:
    """Calculate unrealized FX gains/losses for all foreign currency accounts."""
    resolved_base = (base_currency or await get_effective_base_currency(db, user_id=user_id)).upper()
    accounts = await get_foreign_currency_accounts(db, user_id, resolved_base)

    revaluations: list[AccountRevaluation] = []
    total_unrealized = Decimal("0")

    for account in accounts:
        reval = await calculate_unrealized_fx_for_account(db, account, revaluation_date, resolved_base)
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
        base_currency=resolved_base,
        accounts_revalued=revaluations,
        total_unrealized_gain_loss=total_unrealized,
    )
