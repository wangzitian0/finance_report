"""Account-balance projection — the ledger's read model (data layer).

A leaf sink computed FROM the posted write side: ``calculate_account_balance`` /
``calculate_account_balances`` (signed balances per account type) and
``verify_accounting_equation`` (the equation derived from those balances). Nothing
in ``base/`` or ``extension/`` imports this module — that one-way edge is what keeps
the projection safe (the write side never depends on its own read model).

Balances include only ``posted`` and ``reconciled`` entries and follow account-type
sign rules: Asset/Expense increase on debit; Liability/Equity/Income increase on
credit. Amounts are raw ``Decimal`` (the projection's existing contract).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.ledger.base.validators import ValidationError
from src.ledger.orm.account import Account, AccountType
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine


async def calculate_account_balance(db: AsyncSession, account_id: UUID, user_id: UUID) -> Decimal:
    """
    Calculate the current balance of an account.

    Only includes posted and reconciled journal entries.
    Balance calculation follows account type rules:
    - Asset/Expense: debit increases, credit decreases
    - Liability/Equity/Income: credit increases, debit decreases

    Args:
        db: Database session
        account_id: Account UUID
        user_id: User UUID for security check

    Returns:
        Current account balance
    """
    # Get account
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise ValidationError(f"Account {account_id} not found")
    if account.user_id != user_id:
        raise ValidationError("Account does not belong to user")

    # Sum journal lines for posted/reconciled entries
    # Use separate queries for debit and credit sums
    debit_query = (
        select(func.coalesce(func.sum(JournalLine.amount), Decimal("0")))
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account_id)
        .where(JournalLine.direction == Direction.DEBIT)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    credit_query = (
        select(func.coalesce(func.sum(JournalLine.amount), Decimal("0")))
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account_id)
        .where(JournalLine.direction == Direction.CREDIT)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    debit_result = await db.execute(debit_query)
    credit_result = await db.execute(credit_query)

    total_debit = debit_result.scalar() or Decimal("0")
    total_credit = credit_result.scalar() or Decimal("0")

    # Net balance = debit - credit
    net_balance = total_debit - total_credit

    # Adjust based on account type
    # Asset/Expense: DEBIT increases (positive), CREDIT decreases (negative)
    # Liability/Equity/Income: CREDIT increases (positive), DEBIT decreases (negative)
    if account.type in (AccountType.ASSET, AccountType.EXPENSE):
        return net_balance
    else:
        return -net_balance


async def calculate_account_balances(
    db: AsyncSession,
    accounts: list[Account],
    user_id: UUID,
) -> dict[UUID, Decimal]:
    """Calculate nominal balances in each account's own currency space."""
    return await _calculate_account_balances(
        db,
        accounts,
        user_id,
        amount_expr=JournalLine.amount,
    )


async def calculate_account_balances_in_base_currency(
    db: AsyncSession,
    accounts: list[Account],
    user_id: UUID,
) -> dict[UUID, Decimal]:
    """Calculate balances converted into the configured base currency."""
    base_currency = src.config.settings.base_currency.upper()
    amount_expr: Any = case(
        (func.coalesce(func.upper(JournalLine.currency), base_currency) == base_currency, JournalLine.amount),
        else_=JournalLine.amount * func.coalesce(JournalLine.fx_rate, Decimal("1")),
    )
    return await _calculate_account_balances(
        db,
        accounts,
        user_id,
        amount_expr=amount_expr,
    )


async def _calculate_account_balances(
    db: AsyncSession,
    accounts: list[Account],
    user_id: UUID,
    *,
    amount_expr: Any,
) -> dict[UUID, Decimal]:
    """Calculate balances with one caller-selected currency-space expression.

    Returns a mapping of account_id -> balance, with account type adjustments applied.
    """
    if not accounts:
        return {}

    account_ids = [account.id for account in accounts]
    net_query = (
        select(
            JournalLine.account_id,
            func.coalesce(
                func.sum(
                    case(
                        (JournalLine.direction == Direction.DEBIT, amount_expr),
                        else_=-amount_expr,
                    )
                ),
                Decimal("0"),
            ).label("net_balance"),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(Account.user_id == user_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalLine.account_id.in_(account_ids))
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .group_by(JournalLine.account_id)
    )
    result = await db.execute(net_query)
    net_by_account = {row.account_id: row.net_balance for row in result.all()}

    balances: dict[UUID, Decimal] = {}
    for account in accounts:
        net = net_by_account.get(account.id, Decimal("0"))
        if account.type in (AccountType.ASSET, AccountType.EXPENSE):
            balances[account.id] = net
        else:
            balances[account.id] = -net

    return balances


async def verify_accounting_equation(db: AsyncSession, user_id: UUID) -> bool:
    """
    Verify that the accounting equation holds for a user.

    Assets = Liabilities + Equity + (Income - Expenses)

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        True if equation holds (within tolerance)
    """
    # Get all accounts for user
    result = await db.execute(select(Account).where(Account.user_id == user_id))
    accounts = list(result.scalars().all())

    balances = await calculate_account_balances_in_base_currency(db, accounts, user_id)

    totals = {
        AccountType.ASSET: Decimal("0"),
        AccountType.LIABILITY: Decimal("0"),
        AccountType.EQUITY: Decimal("0"),
        AccountType.INCOME: Decimal("0"),
        AccountType.EXPENSE: Decimal("0"),
    }

    for account in accounts:
        totals[account.type] += balances.get(account.id, Decimal("0"))

    left_side = totals[AccountType.ASSET]
    right_side = (
        totals[AccountType.LIABILITY]
        + totals[AccountType.EQUITY]
        + totals[AccountType.INCOME]
        - totals[AccountType.EXPENSE]
    )

    # Allow small tolerance for rounding errors (must match AGENTS.md: < 0.01)
    return abs(left_side - right_side) < Decimal("0.01")
