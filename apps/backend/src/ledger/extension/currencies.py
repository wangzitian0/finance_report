"""``used_currencies`` — the ledger's contribution to FX-scope discovery (#1641).

The distinct, normalized currency codes the user's ledger actually uses: every
``Account`` currency plus every posted ``JournalLine`` currency. Dissolved out
of the old ``services/market_data_discovery.py`` app-glue: each domain now
publishes its own currencies read, and the delivery layer composes them into
the observed FX pairs it passes to ``pricing``'s crawl (call-convention
inversion — pricing never discovers scopes itself).

The ORM entities (``Account``/``JournalEntry``/``JournalLine``) still live in
the unregistered central ``src/models/`` (#1675 relocates them later); this
module reads only ledger-owned tables.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import normalize_currency_code
from src.ledger.orm.account import Account
from src.ledger.orm.journal import JournalEntry, JournalLine


async def used_currencies(db: AsyncSession, user_id: UUID | None) -> set[str]:
    """The normalized currency codes used by the user's accounts and journal lines."""
    currencies: set[str] = set()

    account_stmt = select(Account.currency)
    if user_id is not None:
        account_stmt = account_stmt.where(Account.user_id == user_id)
    currencies.update(normalize_currency_code(row[0]) for row in (await db.execute(account_stmt)).all() if row[0])

    line_stmt = select(JournalLine.currency).join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
    if user_id is not None:
        line_stmt = line_stmt.where(JournalEntry.user_id == user_id)
    currencies.update(normalize_currency_code(row[0]) for row in (await db.execute(line_stmt)).all() if row[0])

    return currencies
