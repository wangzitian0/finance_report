"""``snapshot_currencies`` — extraction's contribution to FX-scope discovery (#1641).

The distinct, normalized currency codes appearing on the user's imported
``AtomicPosition`` snapshots. Dissolved out of the old
``services/market_data_discovery.py`` app-glue: each domain now publishes its
own currencies read, and the delivery layer composes them into the observed FX
pairs it passes to ``pricing``'s crawl (call-convention inversion — pricing
never discovers scopes itself).

``AtomicPosition`` lives in this package's own ``orm/layer2.py`` (#1675
D4+D5c); this module reads only extraction-owned snapshots.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import normalize_currency_code
from src.extraction.orm.layer2 import AtomicPosition


async def snapshot_currencies(db: AsyncSession, user_id: UUID | None) -> set[str]:
    """The normalized currency codes on the user's imported position snapshots."""
    snapshot_stmt = select(AtomicPosition.currency)
    if user_id is not None:
        snapshot_stmt = snapshot_stmt.where(AtomicPosition.user_id == user_id)
    return {normalize_currency_code(row[0]) for row in (await db.execute(snapshot_stmt)).all() if row[0]}
