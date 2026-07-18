"""Ledger test fixtures that satisfy database-level posting invariants."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.config import settings
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.ledger.extension.anchored_posting import submit_system_journal_entry


async def create_anchored_test_journal_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
    *,
    base_currency: str | None = None,
) -> JournalEntry:
    """Create a draft through the production anchored boundary for low-level tests."""
    return await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        base_currency=base_currency or settings.base_currency,
        operation=f"test-{uuid4().hex[:8]}",
        source_id=source_id,
        source_type=source_type,
        post_immediately=False,
    )


async def create_valid_posted_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date | None = None,
    memo: str = "Posted entry",
    amount: Decimal = Decimal("100.00"),
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
    debit_account_type: AccountType = AccountType.ASSET,
    credit_account_type: AccountType = AccountType.INCOME,
) -> JournalEntry:
    debit_account = Account(
        user_id=user_id,
        name=f"{memo} cash",
        type=debit_account_type,
        currency="SGD",
    )
    credit_account = Account(
        user_id=user_id,
        name=f"{memo} income",
        type=credit_account_type,
        currency="SGD",
    )
    db.add_all([debit_account, credit_account])
    await db.flush()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date or date.today(),
        memo=memo,
        source_type=source_type,
        source_id=source_id,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit_account.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit_account.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency="SGD",
            ),
        ]
    )
    await db.commit()
    await db.refresh(entry)
    return entry


async def create_valid_void_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date | None = None,
    memo: str = "Voided entry",
) -> JournalEntry:
    entry = await create_valid_posted_entry(db, user_id, entry_date=entry_date, memo=memo)
    entry_id = entry.id
    reversal = await create_valid_posted_entry(db, user_id, entry_date=entry_date, memo=f"{memo} reversal")

    entry = await db.get(JournalEntry, entry_id)
    assert entry is not None
    entry.status = JournalEntryStatus.VOID
    entry.void_reason = "test void"
    entry.void_reversal_entry_id = reversal.id
    await db.commit()
    await db.refresh(entry)
    return entry
