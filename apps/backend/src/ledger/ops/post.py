"""``post_entry`` — the ledger's posting verb (an edge in the project DAG).

Takes a balanced :class:`~src.ledger.types.entry.Entry` and persists it as a
posted ``JournalEntry``. The balance invariant is already guaranteed by ``Entry``
construction; this op only translates legs to the storage shape and runs the
existing create + post pipeline (account ownership, fx-rate, system-account, and
posting-status checks remain in ``services.accounting``).

This is the single typed front door for "record a transaction"; callers build an
``Entry`` (their account-selection policy) and hand it here instead of hand-rolling
``lines_data`` dicts.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger.types.entry import Entry
from src.models.journal import JournalEntry, JournalEntrySourceType
from src.services.accounting import create_journal_entry, post_journal_entry


async def post_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    entry_date: date,
    memo: str,
    entry: Entry,
    source_type: JournalEntrySourceType = JournalEntrySourceType.SYSTEM,
    source_id: UUID | None = None,
) -> JournalEntry:
    """Persist a balanced :class:`Entry` and return the posted journal entry."""
    lines_data = [
        {
            "account_id": leg.account_id,
            "direction": leg.direction,
            "amount": leg.money.amount,
            "currency": leg.money.currency.code,
            "fx_rate": leg.fx_rate,
            "event_type": leg.event_type,
            "tags": leg.tags,
        }
        for leg in entry.legs
    ]
    created = await create_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        source_type=source_type,
        source_id=source_id,
    )
    posted = await post_journal_entry(db, created.id, user_id)
    await db.refresh(posted, ["lines"])
    return posted
