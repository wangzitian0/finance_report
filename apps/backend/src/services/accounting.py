"""Accounting service - Core double-entry bookkeeping logic."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
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
from src.services.source_type_priority import normalize_source_type


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
        line_currency = (line.currency or base_currency).upper()
        if line_currency != base_currency and line.fx_rate is None:
            raise ValidationError(f"fx_rate required for currency {line_currency} (base {base_currency})")


def _line_base_amount(line: JournalLine) -> Decimal:
    """Return line amount converted to the configured base currency."""
    base_currency = settings.base_currency.upper()
    line_currency = (line.currency or base_currency).upper()
    if line_currency == base_currency:
        return line.amount
    if line.fx_rate is None:
        raise ValidationError(f"fx_rate required for currency {line_currency} (base {base_currency})")
    return line.amount * line.fx_rate


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

    total_debit = sum(
        (_line_base_amount(line) for line in lines if line.direction == Direction.DEBIT),
        Decimal("0"),
    )
    total_credit = sum(
        (_line_base_amount(line) for line in lines if line.direction == Direction.CREDIT),
        Decimal("0"),
    )

    if abs(total_debit - total_credit) > Decimal("0.01"):
        raise ValidationError(f"Journal entry not balanced: debit={total_debit}, credit={total_credit}")


def validate_journal_posting_invariants(entry: JournalEntry) -> None:
    """Validate the invariants required before an entry can become posted."""
    validate_journal_balance(entry.lines)
    validate_fx_rates(entry.lines)

    for line in entry.lines:
        account = line.account
        if account is None:
            raise ValidationError(f"Account {line.account_id} not found")
        if account.user_id != entry.user_id:
            raise ValidationError("Account does not belong to user")
        if account.is_system and entry.source_type != JournalEntrySourceType.SYSTEM:
            raise ValidationError(
                "System accounts can only be used by system-generated entries. "
                "Manual entries cannot debit/credit system accounts."
            )
        if not account.is_active:
            raise ValidationError(f"Account {account.name} is not active")


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
    *,
    use_base_currency: bool = False,
) -> dict[UUID, Decimal]:
    """
    Calculate balances for multiple accounts in a single query.

    Returns a mapping of account_id -> balance, with account type adjustments applied.
    """
    if not accounts:
        return {}

    account_ids = [account.id for account in accounts]
    if use_base_currency:
        base_currency = settings.base_currency.upper()
        amount_expr: Any = case(
            (func.coalesce(func.upper(JournalLine.currency), base_currency) == base_currency, JournalLine.amount),
            else_=JournalLine.amount * func.coalesce(JournalLine.fx_rate, Decimal("1")),
        )
    else:
        amount_expr = JournalLine.amount

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

    balances = await calculate_account_balances(db, accounts, user_id, use_base_currency=True)

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


async def validate_line_account_ownership(
    db: AsyncSession,
    user_id: UUID,
    account_ids: set[UUID],
) -> dict[UUID, Account]:
    """Load and validate that every line account belongs to the current user."""
    if not account_ids:
        return {}

    result = await db.execute(select(Account).where(Account.id.in_(account_ids)))
    accounts = {account.id: account for account in result.scalars().all()}

    missing = account_ids - set(accounts)
    if missing:
        raise ValidationError(f"Account {next(iter(missing))} not found")

    if any(account.user_id != user_id for account in accounts.values()):
        raise ValidationError("Account does not belong to user")

    return accounts


async def post_opening_balance_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date,
    balances: dict[UUID, Decimal],
    currency: str,
    memo: str = "Opening balances",
) -> JournalEntry:
    """Post a balanced opening-balance entry establishing year-start positions (#949).

    Each supplied account is increased to its opening balance per its normal
    side (assets/expenses debited, liabilities/equity/income credited); the net
    is offset into the system Opening Balance Equity account so the entry
    balances and the accounting equation holds. All amounts are ``Decimal``.
    """
    # Imported lazily so importing this module stays free of the FastAPI/util
    # dependency graph (tooling tests import accounting without those installed).
    from src.services.account_service import get_or_create_opening_balance_equity_account
    from src.utils.money import to_money

    if not balances:
        raise ValidationError("At least one opening balance is required")

    normalized_currency = currency.strip().upper()
    account_ids = list(balances.keys())
    result = await db.execute(select(Account).where(Account.id.in_(account_ids), Account.user_id == user_id))
    accounts = {account.id: account for account in result.scalars().all()}
    missing = [str(account_id) for account_id in account_ids if account_id not in accounts]
    if missing:
        raise ValidationError(f"Unknown or non-owned account(s): {sorted(missing)}")

    # The posted entry is SYSTEM-typed (it offsets into the system equity account),
    # which would otherwise let a caller target any system account (e.g. Processing).
    # Opening balances may only target user-managed accounts.
    system_targets = sorted(str(account.id) for account in accounts.values() if account.is_system)
    if system_targets:
        raise ValidationError(f"Opening balances cannot target system accounts: {system_targets}")

    base_currency = settings.base_currency.strip().upper()
    if normalized_currency != base_currency:
        raise ValidationError(
            f"Opening balances are supported only in the base currency ({base_currency}); got {normalized_currency}."
        )

    # An opening balance establishes a starting position, not a delta: reject when
    # any affected account already has posted/reconciled activity before entry_date,
    # otherwise the posted amount would stack on top of an existing balance.
    prior = await db.execute(
        select(JournalLine.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id.in_(account_ids))
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.entry_date < entry_date)
        .limit(1)
    )
    if prior.first() is not None:
        raise ValidationError(
            "Opening balances must precede all activity for the affected accounts; "
            "one or more already have posted entries before the opening date."
        )

    lines_data: list[dict] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for account_id, raw_amount in balances.items():
        amount = to_money(raw_amount)
        if amount <= Decimal("0"):
            raise ValidationError("Opening balance amounts must be positive")
        account = accounts[account_id]
        if (account.currency or "").strip().upper() != normalized_currency:
            raise ValidationError(
                f"Opening balance currency {normalized_currency} does not match the currency "
                f"of account {account_id} ({account.currency}); lines must not be mis-stamped."
            )
        if account.type in (AccountType.ASSET, AccountType.EXPENSE):
            direction = Direction.DEBIT
            total_debit += amount
        else:
            direction = Direction.CREDIT
            total_credit += amount
        lines_data.append(
            {"account_id": account_id, "direction": direction, "amount": amount, "currency": normalized_currency}
        )

    net = total_debit - total_credit
    if net != Decimal("0"):
        equity_account = await get_or_create_opening_balance_equity_account(db, user_id, normalized_currency)
        lines_data.append(
            {
                "account_id": equity_account.id,
                "direction": Direction.CREDIT if net > 0 else Direction.DEBIT,
                "amount": abs(net),
                "currency": normalized_currency,
            }
        )

    # SYSTEM-typed: the guided flow orchestrates this entry and it offsets into
    # the system Opening Balance Equity account, which manual entries may not touch.
    entry = await create_journal_entry(
        db,
        user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        source_type=JournalEntrySourceType.SYSTEM,
    )
    return await post_journal_entry(db, entry.id, user_id)


async def get_opening_balance_readiness(db: AsyncSession, user_id: UUID) -> dict:
    """Detect whether a user's balance sheet may be silently incomplete (#949 / AC2.16.1).

    The everyday-user persona who already owns assets/liabilities on day one will,
    without recording opening balances, get a balance sheet that looks right but
    omits the starting position. This returns ``needs_opening_balance=True`` when
    the user has posted activity but no opening-balance entry on or before the
    earliest such activity, so the UI can nudge them before they ship incomplete
    numbers.
    """
    posted = (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)

    # Opening-balance entries are exactly the journal entries with a line on the
    # user's system-managed Opening Balance Equity account (code 3199).
    opening_entry_ids = (
        select(JournalLine.journal_entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(
            Account.user_id == user_id,
            Account.is_system.is_(True),
            Account.code == "3199",
        )
    )

    # Earliest "real" activity = earliest posted/reconciled entry that is not an
    # opening-balance entry (statements, manual entries, FX, processing, ...).
    earliest_activity = await db.scalar(
        select(func.min(JournalEntry.entry_date)).where(
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_(posted),
            JournalEntry.id.not_in(opening_entry_ids),
        )
    )
    earliest_opening = await db.scalar(
        select(func.min(JournalEntry.entry_date)).where(
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_(posted),
            JournalEntry.id.in_(opening_entry_ids),
        )
    )

    has_activity = earliest_activity is not None
    has_opening_before = earliest_opening is not None and (
        earliest_activity is None or earliest_opening <= earliest_activity
    )
    return {
        "needs_opening_balance": has_activity and not has_opening_before,
        "has_activity": has_activity,
        "has_opening_entry": earliest_opening is not None,
        "earliest_activity_date": earliest_activity,
    }


async def create_journal_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
) -> JournalEntry:
    await validate_line_account_ownership(
        db,
        user_id,
        {line_data["account_id"] for line_data in lines_data},
    )

    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=normalize_source_type(source_type),
        source_id=source_id,
    )

    lines: list[JournalLine] = []
    default_currency = settings.base_currency.upper()
    for line_data in lines_data:
        line = JournalLine(
            journal_entry_id=entry.id,
            account_id=line_data["account_id"],
            direction=line_data["direction"],
            amount=line_data["amount"],
            currency=(line_data.get("currency") or default_currency).upper(),
            fx_rate=line_data.get("fx_rate"),
            event_type=line_data.get("event_type"),
            tags=line_data.get("tags"),
        )
        lines.append(line)

    validate_journal_balance(lines)
    validate_fx_rates(lines)

    db.add(entry)
    await db.flush()

    for line in lines:
        line.journal_entry_id = entry.id
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

    validate_journal_posting_invariants(entry)

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
