"""Journal write pipeline — the ledger's persistence (store) core.

`create_journal_entry` / `post_journal_entry` / `void_journal_entry` plus the
balance/fx/ownership validators that gate them. Moved here from
`services.accounting` so the ledger owns its own posting pipeline: `ledger.ops`
depends *down* on this module instead of *up* on a service, dissolving the
`ledger ↔ services.accounting` import cycle. `services.accounting` re-exports
these names for its existing callers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.models import (
    Account,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.money import Money
from src.services.source_type_priority import normalize_source_type


class AccountingError(Exception):
    """Base exception for accounting errors."""


class ValidationError(AccountingError):
    """Validation error for accounting operations."""


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


def _line_base_amount(line: JournalLine) -> Money:
    """Return the line value converted to the configured base currency, as Money."""
    base_currency = settings.base_currency.upper()
    line_money = line.money  # currency resolved via the single SSOT (None -> base)
    if line_money.currency.code == base_currency:
        return line_money
    if line.fx_rate is None:
        raise ValidationError(f"fx_rate required for currency {line_money.currency.code} (base {base_currency})")
    return Money(line.amount * line.fx_rate, base_currency)


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

    # All per-line amounts are in base currency here, so Money.sum is single-currency;
    # a cross-currency mix would raise instead of silently summing.
    total_debit = Money.sum(
        (_line_base_amount(line) for line in lines if line.direction == Direction.DEBIT),
        currency=settings.base_currency,
    )
    total_credit = Money.sum(
        (_line_base_amount(line) for line in lines if line.direction == Direction.CREDIT),
        currency=settings.base_currency,
    )

    if abs((total_debit - total_credit).amount) > Decimal("0.01"):
        raise ValidationError(f"Journal entry not balanced: debit={total_debit.amount}, credit={total_credit.amount}")


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
