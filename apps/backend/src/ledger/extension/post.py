"""``post_entry`` — the ledger's posting verb (a domain service; an extension edge).

Takes a balanced :class:`~src.ledger.base.types.entry.Entry` and persists it as a
posted ``JournalEntry`` through the :class:`~src.ledger.base.repository.JournalRepository`
port. The balance invariant is already guaranteed by ``Entry`` construction; this
service only translates legs to the storage shape and runs create + post via the
port (account ownership, fx-rate, system-account, and posting-status checks live in
the adapter / base validators).

This is the single typed front door for "record a transaction"; callers build an
``Entry`` (their account-selection policy) and hand it here instead of hand-rolling
``lines_data`` dicts. ``post_entry`` depends on the abstract repository port
(mechanism B), defaulting to the ``AsyncSession`` adapter so existing callers pass
``db`` unchanged while tests can inject an in-memory fake.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger.base.repository import JournalRepository
from src.ledger.base.types.entry import Entry
from src.ledger.extension.repository import SqlJournalRepository
from src.models.journal import JournalEntry, JournalEntrySourceType


async def post_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    entry_date: date,
    memo: str,
    entry: Entry,
    source_type: JournalEntrySourceType = JournalEntrySourceType.SYSTEM,
    source_id: UUID | None = None,
    repo: JournalRepository | None = None,
) -> JournalEntry:
    """Persist a balanced :class:`Entry` and return the posted journal entry.

    ``repo`` is the persistence port; when omitted it defaults to the
    ``AsyncSession`` adapter over ``db`` (dependency inversion, mechanism B —
    tests inject a fake, production passes the session).
    """
    repository: JournalRepository = repo if repo is not None else SqlJournalRepository(db)
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
    created = await repository.create(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        source_type=source_type,
        source_id=source_id,
    )
    posted = await repository.post(created.id, user_id)
    await db.refresh(posted, ["lines"])
    return posted
