"""Unrealized FX gain/loss calculation for foreign-currency asset and liability accounts.

This module only reads. It compares each account's historical cost with its
spot-rate value and returns the difference to reporting. It books no journal
entry: reporting recomputes the value on every report (#2774).
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit import JournalEntrySourceType
from src.ledger.orm.account import Account, AccountType
from src.ledger.orm.journal import (
    Direction,
    JournalEntry,
    JournalLine,
    active_journal_entry_filter,
)
from src.observability import get_logger


class FxRateProvider(Protocol):
    def __call__(
        self,
        db: AsyncSession,
        base_currency: str,
        quote_currency: str,
        rate_date: date,
        *,
        lazy_load: bool = False,
    ) -> Awaitable[Decimal]: ...


logger = get_logger(__name__)
settings = src.config.settings

REVALUATION_ACCOUNT_TYPES = (AccountType.ASSET, AccountType.LIABILITY)


class RevaluationError(Exception):
    pass


class _FxRateProviderNotRegisteredError(Exception):
    """Placeholder bound to :data:`FxRateError` before wiring.

    Never raised by anything, so a pre-wiring ``except FxRateError`` simply
    matches nothing instead of crashing on a non-exception sentinel (mirrors
    ``reporting.extension.fx_gateway`` and ``extraction.extension.review_queue``).
    """


# ``ledger`` and ``pricing`` are both L3 domains; pricing's own
# repository/manual-valuation reads need extraction's published ORM entities,
# and extraction needs ledger's Account/JournalEntry types, so a direct
# ledger -> pricing import here would make depends_on cyclic
# (ledger -> pricing -> extraction -> ledger). Same inversion as
# ``reporting.extension.fx_gateway`` (#1666) and
# ``extraction.extension.review_queue`` (#1675 D5c): the port lives here,
# main.py (L4) wires the real pricing.get_exchange_rate/PricingError at
# startup; tests wire it directly.
_get_exchange_rate: FxRateProvider | None = None

#: The injected FX-unavailable exception class (``src.pricing.PricingError``
#: today). Reference late-bound as ``fx_revaluation.PricingError``.
PricingError: type[Exception] = _FxRateProviderNotRegisteredError


def register_fx_revaluation_provider(
    get_exchange_rate: FxRateProvider,
    *,
    fx_rate_error: type[Exception],
) -> None:
    """Wire the FX-rate lookup (see module note above)."""
    global _get_exchange_rate, PricingError
    _get_exchange_rate = get_exchange_rate
    PricingError = fx_rate_error


def _require_fx_rate_provider() -> FxRateProvider:
    if _get_exchange_rate is None:
        raise RuntimeError(
            "fx_revaluation.register_fx_revaluation_provider() was never called — "
            "main.py wires it at startup; a test exercising this path must call it too."
        )
    return _get_exchange_rate


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
) -> list[Account]:
    """Get all asset/liability accounts with non-base currency."""
    base_currency = settings.base_currency.upper()

    stmt = (
        select(Account)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(REVALUATION_ACCOUNT_TYPES))
        .where(Account.currency != base_currency)
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
        .where(active_journal_entry_filter(JournalEntry))
        .where(JournalEntry.source_type != JournalEntrySourceType.FX_REVALUATION)
    )

    result = await db.execute(stmt)
    base_currency = settings.base_currency.upper()
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for row in result.all():
        if row.fx_rate is None:
            try:
                rate = await _require_fx_rate_provider()(db, account.currency, base_currency, row.entry_date)
            except PricingError:
                logger.warning(
                    "Historical FX rate missing for revaluation cost basis, falling back to revaluation-date rate",
                    account_id=str(account.id),
                    currency=account.currency,
                    entry_date=row.entry_date.isoformat(),
                    revaluation_date=as_of_date.isoformat(),
                )
                rate = await _require_fx_rate_provider()(db, account.currency, base_currency, as_of_date)
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
        current_rate = await _require_fx_rate_provider()(
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

    This is the main entry point for the unrealized FX calculation. It creates
    no journal entries.
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
    )
