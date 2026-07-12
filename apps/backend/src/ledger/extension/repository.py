"""Journal write adapter — the ledger's persistence edge (extension layer).

The concrete, ``AsyncSession``-backed implementation of the
:class:`~src.ledger.base.repository.JournalRepository` port: ``create`` /
``post`` / ``void`` plus the async account-ownership check that gates them. This
is mechanism B — the pure core (``base/``) depends on the abstract port; the
impure I/O lives here and depends back on it.

The module-level ``create_journal_entry`` / ``post_journal_entry`` /
``void_journal_entry`` functions are the published functional surface (re-exported
from ``src.ledger``); :class:`SqlJournalRepository` is the port adapter that wraps
them so ``post_entry`` can depend on the injectable port.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import src.config
from src.audit import JournalEntrySourceType, normalize_source_type
from src.ledger.base.validators import (
    ValidationError,
    validate_fx_rates,
    validate_journal_balance,
    validate_journal_posting_invariants,
)
from src.ledger.orm.account import Account
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine


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
    default_currency = src.config.settings.base_currency.upper()
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


class SqlJournalRepository:
    """``AsyncSession``-backed :class:`~src.ledger.base.repository.JournalRepository`.

    Wraps the module-level write functions so ``post_entry`` can depend on the
    abstract port (mechanism B) while production wiring stays a thin pass-through
    over the one ``AsyncSession`` owned by the caller's transaction boundary.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: UUID,
        entry_date: date,
        memo: str,
        lines_data: list[dict],
        source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
        source_id: UUID | None = None,
    ) -> JournalEntry:
        return await create_journal_entry(
            self._db,
            user_id,
            entry_date,
            memo,
            lines_data,
            source_type=source_type,
            source_id=source_id,
        )

    async def post(self, entry_id: UUID, user_id: UUID) -> JournalEntry:
        return await post_journal_entry(self._db, entry_id, user_id)

    async def void(self, entry_id: UUID, reason: str, user_id: UUID) -> JournalEntry:
        return await void_journal_entry(self._db, entry_id, reason, user_id)
