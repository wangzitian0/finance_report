"""``processing`` — the Processing account's impure verbs (extension layer).

The I/O half of the in-transit (Processing) account. Depends on ``AsyncSession`` +
the ORM and on the pure policy in ``ledger.base.processing``:

- ``get_or_create_processing_account`` — acquire (or first-time create) the per-user
  Processing ``Account`` row (the aggregate's persistence / repository edge);
- ``create_transfer_out_entry`` / ``create_transfer_in_entry`` — post a transfer leg
  (Dr Processing / Cr source, resp. Dr destination / Cr Processing), guarding balance
  through :class:`~src.ledger.base.types.entry.Entry` before persisting;
- ``find_transfer_pairs`` — the pairing domain service: scores persisted Processing
  entries pairwise and returns matches above the confidence threshold;
- ``get_processing_balance`` / ``get_unpaired_transfers`` /
  ``list_processing_transfer_legs`` — read projections over the persisted entries.

Reconciliation / reporting consume these through the published ``src.ledger``
interface (by id/event), never via a shared cross-domain transaction or FK.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.audit.money import Money
from src.ledger.base.processing import (
    AUTO_PAIR_THRESHOLD,
    MAX_DATE_DIFF_DAYS,
    PROCESSING_ACCOUNT_CODE,
    PROCESSING_ACCOUNT_DESCRIPTION,
    PROCESSING_ACCOUNT_NAME,
    PROCESSING_ACCOUNT_TYPE,
    TransferPair,
    _calculate_pair_confidence,
    _validate_transfer_params,
)
from src.ledger.base.types.entry import Entry
from src.ledger.extension.post import post_entry
from src.ledger.orm.account import Account
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine


async def get_or_create_processing_account(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
) -> Account:
    """Get or create the Processing virtual account for a user."""
    result = await db.execute(
        select(Account).where(
            Account.user_id == user_id,
            Account.is_system == True,  # noqa: E712
            Account.code == PROCESSING_ACCOUNT_CODE,
        )
    )
    account = result.scalar_one_or_none()

    if not account:
        # Create Processing account
        account = Account(
            user_id=user_id,
            name=PROCESSING_ACCOUNT_NAME,
            code=PROCESSING_ACCOUNT_CODE,
            type=PROCESSING_ACCOUNT_TYPE,
            currency=currency,
            is_system=True,
            description=PROCESSING_ACCOUNT_DESCRIPTION,
        )
        db.add(account)
        await db.flush()
        await db.refresh(account)

    return account


async def find_transfer_pairs(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
    description_scorer: Callable[[str | None, str | None], float],
    threshold: int = AUTO_PAIR_THRESHOLD,
    max_entries: int = 500,
) -> list[TransferPair]:
    """Find matching transfer pairs based on confidence scoring.
    and attempts to match them based on amount, description, and date proximity.
    Note: The pairing algorithm is O(n²) where n = max(out_entries, in_entries).
    The max_entries parameter limits the number of entries processed to prevent
    performance degradation with high transaction volumes.

    Args:
        db: Database session
        user_id: User ID to search transfers for
        threshold: Minimum confidence score (default: 85)
        max_entries: Maximum number of entries to process per side (default: 500)
    Returns:
        List of TransferPair objects with confidence >= threshold
    """
    # Get Processing account
    processing_account = await get_or_create_processing_account(db, user_id, currency=currency)

    # Find all journal entries involving Processing account
    result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .join(JournalLine, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.source_type == JournalEntrySourceType.SYSTEM)
        .where(JournalLine.account_id == processing_account.id)
    )
    entries = result.scalars().unique().all()

    # Separate OUT and IN entries
    out_entries = []
    in_entries = []

    for entry in entries:
        for line in entry.lines:
            if line.account_id == processing_account.id:
                # Transfer OUT: Processing is DEBITED
                if line.direction == Direction.DEBIT:
                    out_entries.append(entry)
                # Transfer IN: Processing is CREDITED
                elif line.direction == Direction.CREDIT:
                    in_entries.append(entry)
                break

    # Limit entries to prevent O(n²) performance degradation with large datasets
    out_entries = out_entries[:max_entries]
    in_entries = in_entries[:max_entries]

    # Find pairs with confidence >= threshold
    pairs: list[TransferPair] = []
    matched_in_entries: set[int] = set()  # Track already-matched IN entries
    for out_entry in out_entries:
        best_match: TransferPair | None = None
        for in_entry in in_entries:
            if id(in_entry) in matched_in_entries:
                continue

            confidence, breakdown = _calculate_pair_confidence(
                out_entry,
                in_entry,
                processing_account.id,
                description_scorer=description_scorer,
            )
            if confidence >= threshold:
                pair = TransferPair(
                    out_entry=out_entry,
                    in_entry=in_entry,
                    confidence=confidence,
                    score_breakdown=breakdown,
                )
                # Keep only the best match for this out_entry
                if best_match is None or confidence > best_match.confidence:
                    best_match = pair
        if best_match:
            pairs.append(best_match)
            matched_in_entries.add(id(best_match.in_entry))

    return pairs


async def create_transfer_out_entry(
    db: AsyncSession,
    user_id: UUID,
    source_account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
    *,
    currency: str,
) -> JournalEntry:
    """Create a Transfer OUT journal entry.

    Transfer OUT: DEBIT Processing, CREDIT source account

    Args:
        db: Database session
        user_id: User ID
        source_account_id: Account ID where funds are leaving
        amount: Transfer amount
        txn_date: Transaction date
        description: Transfer description

    Returns:
        Created JournalEntry (not yet committed)
    """
    return await _create_transfer_entry(
        db,
        user_id=user_id,
        account_id=source_account_id,
        amount=amount,
        txn_date=txn_date,
        description=description,
        currency=currency,
        direction="OUT",
    )


async def create_transfer_in_entry(
    db: AsyncSession,
    user_id: UUID,
    dest_account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
    *,
    currency: str,
) -> JournalEntry:
    """Create a Transfer IN journal entry.

    Transfer IN: DEBIT destination account, CREDIT Processing

    Args:
        db: Database session
        user_id: User ID
        dest_account_id: Account ID where funds are arriving
        amount: Transfer amount
        txn_date: Transaction date
        description: Transfer description

    Returns:
        Created JournalEntry (not yet committed)
    """
    return await _create_transfer_entry(
        db,
        user_id=user_id,
        account_id=dest_account_id,
        amount=amount,
        txn_date=txn_date,
        description=description,
        currency=currency,
        direction="IN",
    )


async def _create_transfer_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
    currency: str,
    direction: str,
) -> JournalEntry:
    """Build one transfer leg and route persistence through ledger's front door."""
    _validate_transfer_params(amount, description)
    processing_account = await get_or_create_processing_account(
        db,
        user_id,
        currency=currency,
    )
    if direction == "OUT":
        debit_id, credit_id = processing_account.id, account_id
    else:
        debit_id, credit_id = account_id, processing_account.id
    entry = Entry.transfer(
        debit=debit_id,
        credit=credit_id,
        money=Money(amount, currency),
    )
    return await post_entry(
        db,
        user_id=user_id,
        entry_date=txn_date,
        memo=f"Transfer {direction}: {description}",
        entry=entry,
        source_type=JournalEntrySourceType.SYSTEM,
    )


async def get_processing_balance(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
) -> Decimal:
    """Get current balance of Processing account.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        Processing account balance (Decimal)
    """
    processing_account = await get_or_create_processing_account(db, user_id, currency=currency)

    # Get all journal lines for Processing account
    result = await db.execute(
        select(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == processing_account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )
    lines = result.scalars().all()

    # Calculate balance (Asset account: debit - credit). Lines are single-currency
    # (the account's own); Money.sum infers it and would raise on a cross-currency mix.
    line_monies = [line.money if line.direction == Direction.DEBIT else -line.money for line in lines]
    return Money.sum(line_monies).amount if line_monies else Decimal("0")


async def get_unpaired_transfers(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
    days_threshold: int = MAX_DATE_DIFF_DAYS,
) -> list[dict]:
    """Get unpaired transfer entries (Processing balance != 0).

    Returns ALL entries involving Processing account to show user what's unpaired.
    The days_threshold is for alerting purposes only, not filtering.

    Args:
        db: Database session
        user_id: User ID
        days_threshold: Alert threshold (unused in current implementation)
    Returns:
        List of dicts with keys: entry_id, direction, amount, date, description
    """
    processing_account = await get_or_create_processing_account(db, user_id, currency=currency)
    # Get all journal lines for Processing account
    result = await db.execute(
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == processing_account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.source_type == JournalEntrySourceType.SYSTEM)
        .order_by(JournalEntry.entry_date.desc())
    )
    rows = result.all()

    # Build list of unpaired transfers
    unpaired = []
    for line, entry in rows:
        unpaired.append(
            {
                "entry_id": entry.id,
                "direction": "OUT" if line.direction == Direction.DEBIT else "IN",
                "amount": line.amount,
                "date": entry.entry_date,
                "description": entry.memo or "",
            }
        )

    return unpaired


async def list_processing_transfer_legs(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
) -> list[dict]:
    processing_account = await get_or_create_processing_account(db, user_id, currency=currency)

    result = await db.execute(
        select(JournalEntry)
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == processing_account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.source_type == JournalEntrySourceType.SYSTEM)
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
        .order_by(JournalEntry.entry_date.desc())
    )
    entries = result.scalars().unique().all()

    today = date.today()
    legs: list[dict] = []
    for entry in entries:
        processing_line = next(
            (line for line in entry.lines if line.account_id == processing_account.id),
            None,
        )
        if processing_line is None:
            continue

        other_line = next(
            (line for line in entry.lines if line.account_id != processing_account.id),
            None,
        )
        other_account: Account | None = other_line.account if other_line else None
        other_name = other_account.name if other_account else "(unknown)"
        currency = other_account.currency if other_account else processing_account.currency

        if processing_line.direction == Direction.DEBIT:
            from_account = other_name
            to_account = "(unmatched destination)"
        else:
            from_account = "(unmatched source)"
            to_account = other_name

        legs.append(
            {
                "entry_id": entry.id,
                "from_account": from_account,
                "to_account": to_account,
                "amount": processing_line.amount,
                "currency": currency,
                "initiated_date": entry.entry_date,
                "days_outstanding": (today - entry.entry_date).days,
                "description": entry.memo or "",
            }
        )

    return legs
