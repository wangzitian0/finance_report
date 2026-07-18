"""Private journal persistence implementation for the anchored command boundary.

Only ``anchored_posting`` may create a new financial fact through this module's
private ``_create_anchored_journal_entry`` sink. Posting and voiding remain published
lifecycle verbs; voiding creates its reversal through the system anchored command.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import src.config
from src.audit import JournalEntrySourceType, normalize_source_type
from src.audit.money import Currency
from src.ledger.base.decision_anchor import DecisionAnchor
from src.ledger.base.validators import (
    ValidationError,
    validate_fx_rates,
    validate_journal_balance,
    validate_journal_posting_invariants,
)
from src.ledger.orm.account import Account
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryAuthorityState, JournalEntryStatus, JournalLine


async def _set_transaction_base_currency(db: AsyncSession, base_currency: str | None) -> str:
    """Keep PostgreSQL's deferred ledger invariant aligned with Python validation."""
    normalized = Currency.of(base_currency or src.config.settings.base_currency).code
    await db.execute(
        text("SELECT set_config('finance_report.base_currency', :base_currency, true)"),
        {"base_currency": normalized},
    )
    return normalized


def _historical_reversal_base_currency(
    lines: list[JournalLine],
    *,
    fallback_base_currency: str | None,
) -> str:
    """Recover the base currency under which the posted lines were validated."""
    fallback = Currency.of(fallback_base_currency or src.config.settings.base_currency).code
    fx_free_currencies = {Currency.of(line.currency or fallback).code for line in lines if line.fx_rate is None}
    if not fx_free_currencies:
        raise ValidationError("Cannot determine historical base currency: all lines have FX rates")
    if len(fx_free_currencies) > 1:
        currencies = ", ".join(sorted(fx_free_currencies))
        raise ValidationError(f"Cannot determine historical base currency from FX-free lines: {currencies}")

    historical_base = next(iter(fx_free_currencies), fallback)
    validate_journal_balance(lines, base_currency=historical_base)
    validate_fx_rates(lines, base_currency=historical_base)
    return historical_base


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


async def _create_anchored_journal_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
    *,
    base_currency: str | None = None,
    decision_anchor: DecisionAnchor,
) -> JournalEntry:
    base_currency = await _set_transaction_base_currency(db, base_currency)
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
        decision_anchor_id=decision_anchor.decision_id,
        decision_authority_state=JournalEntryAuthorityState.ANCHORED,
    )

    lines: list[JournalLine] = []
    default_currency = base_currency
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

    validate_journal_balance(lines, base_currency=base_currency)
    validate_fx_rates(lines, base_currency=base_currency)

    db.add(entry)
    await db.flush()

    for line in lines:
        line.journal_entry_id = entry.id
        db.add(line)

    await db.flush()
    await db.refresh(entry, ["lines"])
    return entry


async def post_journal_entry(
    db: AsyncSession,
    entry_id: UUID,
    user_id: UUID,
    *,
    base_currency: str | None = None,
) -> JournalEntry:
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
    base_currency = await _set_transaction_base_currency(db, base_currency)
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

    validate_journal_posting_invariants(entry, base_currency=base_currency)

    entry.status = JournalEntryStatus.POSTED
    entry.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(entry)

    return entry


async def void_journal_entry(
    db: AsyncSession,
    entry_id: UUID,
    reason: str,
    user_id: UUID,
    *,
    base_currency: str | None = None,
) -> JournalEntry:
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
    historical_base = _historical_reversal_base_currency(
        entry.lines,
        fallback_base_currency=base_currency,
    )
    await _set_transaction_base_currency(db, historical_base)

    # Keep a correction on the same anchored command boundary as every other
    # new financial fact. The original entry id is the immutable source identity.
    from src.ledger.extension.anchored_posting import submit_system_journal_entry

    reversal_entry = await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=date.today(),
        memo=f"VOID: {entry.memo}",
        lines_data=[
            {
                "account_id": line.account_id,
                "direction": Direction.CREDIT if line.direction == Direction.DEBIT else Direction.DEBIT,
                "amount": line.amount,
                "currency": line.currency,
                "fx_rate": line.fx_rate,
                "event_type": line.event_type,
                "tags": line.tags,
            }
            for line in entry.lines
        ],
        base_currency=historical_base,
        operation="void-reversal",
        source_id=entry.id,
    )

    # Update original entry
    entry.status = JournalEntryStatus.VOID
    entry.void_reason = reason
    entry.void_reversal_entry_id = reversal_entry.id
    entry.updated_at = datetime.now(UTC)

    await db.flush()
    # The lifecycle service returns a complete aggregate. Callers may commit
    # before inspecting reversal lines, where async lazy loading is invalid.
    await db.refresh(reversal_entry, ["lines"])
    return reversal_entry
