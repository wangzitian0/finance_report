"""Accounting service - Core double-entry bookkeeping logic."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)


class AccountingError(Exception):
    """Base exception for accounting errors."""

    pass


class ValidationError(AccountingError):
    """Validation error for accounting operations."""

    pass


def validate_fx_rates(lines: list[JournalLine]) -> None:
    """
    Validate FX rate requirements for multi-currency lines.

    Requires fx_rate when line currency differs from base currency.
    """
    base_currency = settings.base_currency.upper()
    for line in lines:
        if line.currency.upper() != base_currency and line.fx_rate is None:
            raise ValidationError(f"fx_rate required for currency {line.currency} (base {base_currency})")


def validate_journal_balance(lines: list[JournalLine]) -> None:
    """
    Validate that journal entry lines are balanced (debit = credit).

    Args:
        lines: List of journal lines to validate

    Raises:
        ValidationError: If debits and credits don't balance
    """
    if len(lines) < 2:
        raise ValidationError("Journal entry must have at least 2 lines")

    total_debit = sum(line.amount for line in lines if line.direction == Direction.DEBIT)
    total_credit = sum(line.amount for line in lines if line.direction == Direction.CREDIT)

    if abs(total_debit - total_credit) > Decimal("0.01"):
        raise ValidationError(f"Journal entry not balanced: debit={total_debit}, credit={total_credit}")


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
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    credit_query = (
        select(func.coalesce(func.sum(JournalLine.amount), Decimal("0")))
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account_id)
        .where(JournalLine.direction == Direction.CREDIT)
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
    """
    Calculate balances for multiple accounts in a single query.

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
                        (JournalLine.direction == Direction.DEBIT, JournalLine.amount),
                        else_=-JournalLine.amount,
                    )
                ),
                Decimal("0"),
            ).label("net_balance"),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(Account.user_id == user_id)
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
    accounts = result.scalars().all()

    balances = await calculate_account_balances(db, accounts, user_id)

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


async def create_journal_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=source_type,
        source_id=source_id,
    )
    db.add(entry)
    await db.flush()

    lines: list[JournalLine] = []
    for line_data in lines_data:
        line = JournalLine(
            journal_entry_id=entry.id,
            account_id=line_data["account_id"],
            direction=line_data["direction"],
            amount=line_data["amount"],
            currency=line_data.get("currency", "SGD"),
            fx_rate=line_data.get("fx_rate"),
            event_type=line_data.get("event_type"),
            tags=line_data.get("tags"),
        )
        lines.append(line)

    validate_fx_rates(lines)

    for line in lines:
        db.add(line)

    await db.flush()
    await db.refresh(entry, ["lines"])
    return entry


async def post_journal_entry(db: AsyncSession, entry_id: UUID, user_id: UUID) -> JournalEntry:
    """
    Post a journal entry from draft to posted status.

    Args:
        db: Database session
        entry_id: Journal entry UUID
        user_id: User UUID for security check

    Returns:
        Posted journal entry

    Raises:
        ValidationError: If entry cannot be posted
    """
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id)
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise ValidationError(f"Journal entry {entry_id} not found")
    if entry.user_id != user_id:
        raise ValidationError("Journal entry does not belong to user")
    if entry.status != JournalEntryStatus.DRAFT:
        raise ValidationError(f"Can only post draft entries, current status: {entry.status}")

    validate_journal_balance(entry.lines)
    validate_fx_rates(entry.lines)

    # Validate Processing account usage (Anti-pattern A from processing_account.md)
    for line in entry.lines:
        if line.account.is_system and line.account.code == "1199":
            if entry.source_type != JournalEntrySourceType.SYSTEM:
                raise ValidationError(
                    "Processing account can only be used by system-generated entries. "
                    "Manual entries cannot debit/credit the Processing account."
                )

    for line in entry.lines:
        if not line.account.is_active:
            raise ValidationError(f"Account {line.account.name} is not active")

    entry.status = JournalEntryStatus.POSTED
    entry.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(entry)

    return entry


async def void_journal_entry(db: AsyncSession, entry_id: UUID, reason: str, user_id: UUID) -> JournalEntry:
    """
    Void a posted journal entry by creating a reversal entry.

    Args:
        db: Database session
        entry_id: Journal entry UUID to void
        reason: Reason for voiding
        user_id: User UUID for security check

    Returns:
        Reversal journal entry

    Raises:
        ValidationError: If entry cannot be voided
    """
    # Get original entry
    result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry_id))
    entry = result.scalar_one_or_none()

    if not entry:
        raise ValidationError(f"Journal entry {entry_id} not found")
    if entry.user_id != user_id:
        raise ValidationError("Journal entry does not belong to user")
    if entry.status != JournalEntryStatus.POSTED:
        raise ValidationError("Can only void posted entries")

    # Load lines
    await db.refresh(entry, ["lines"])

    # Create reversal entry
    reversal_entry = JournalEntry(
        user_id=user_id,
        entry_date=date.today(),
        memo=f"VOID: {entry.memo}",
        source_type=JournalEntrySourceType.SYSTEM,
        status=JournalEntryStatus.POSTED,
    )
    db.add(reversal_entry)
    await db.flush()

    # Create reversed lines
    for line in entry.lines:
        reversed_direction = Direction.CREDIT if line.direction == Direction.DEBIT else Direction.DEBIT
        reversal_line = JournalLine(
            journal_entry_id=reversal_entry.id,
            account_id=line.account_id,
            direction=reversed_direction,
            amount=line.amount,
            currency=line.currency,
            fx_rate=line.fx_rate,
            event_type=line.event_type,
            tags=line.tags,
        )
        db.add(reversal_line)

    # Update original entry
    entry.status = JournalEntryStatus.VOID
    entry.void_reason = reason
    entry.void_reversal_entry_id = reversal_entry.id
    entry.updated_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(reversal_entry, ["lines"])

    return reversal_entry
