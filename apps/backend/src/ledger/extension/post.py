"""``post_entry`` — deterministic system commands through the anchored port."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.ledger.base.types.entry import Entry
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from src.ledger.orm.journal import JournalEntry


async def post_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    entry_date: date,
    memo: str,
    entry: Entry,
    base_currency: str | None = None,
    source_id: UUID | None = None,
    operation: str = "typed-post-entry",
) -> JournalEntry:
    """Persist a balanced :class:`Entry` under a deterministic system decision."""
    if base_currency is None:
        # Compatibility for callers outside this slice; migrated delivery paths
        # pass their persisted effective base explicitly.
        base_currency = src.config.settings.base_currency
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
    posted = await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        base_currency=base_currency,
        operation=operation,
        source_id=source_id,
    )
    await db.refresh(posted, ["lines"])
    return posted
