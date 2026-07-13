"""Portfolio's contribution to market-data scope discovery (#1641).

``active_stock_symbols`` (which symbols does the user hold?) and
``position_currencies`` (which currencies do those holdings carry?) are
"what does this user hold" questions — portfolio's own domain. Dissolved out
of the old ``services/market_data_discovery.py`` app-glue: each domain now
publishes its own read, and the delivery layer composes them into the scopes
it passes to ``pricing``'s crawl (call-convention inversion — pricing never
discovers scopes itself).

``ManagedPosition`` lives in ``extraction``'s ``orm/layer3.py`` (#1675
D4+D5c — extraction owns the fact family's ORM); this module reads only
portfolio-owned positions.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import normalize_currency_code
from src.audit.quantity import Quantity
from src.extraction.orm.layer3 import ManagedPosition, PositionStatus
from src.pricing import MARKET_DATA_QUANTITY_UNIT


async def active_stock_symbols(db: AsyncSession, user_id: UUID | None) -> list[str]:
    """The distinct asset identifiers of the user's active, non-zero positions."""
    stmt = (
        select(ManagedPosition.asset_identifier)
        .where(ManagedPosition.status == PositionStatus.ACTIVE)
        .where(ManagedPosition.quantity != Quantity.zero(MARKET_DATA_QUANTITY_UNIT).quantize().value)
        .order_by(ManagedPosition.asset_identifier)
    )
    if user_id is not None:
        stmt = stmt.where(ManagedPosition.user_id == user_id)
    result = await db.execute(stmt)
    return sorted({row[0].strip().upper() for row in result.all() if row[0]})


async def position_currencies(db: AsyncSession, user_id: UUID | None) -> set[str]:
    """The normalized currency codes on the user's managed positions."""
    position_stmt = select(ManagedPosition.currency)
    if user_id is not None:
        position_stmt = position_stmt.where(ManagedPosition.user_id == user_id)
    return {normalize_currency_code(row[0]) for row in (await db.execute(position_stmt)).all() if row[0]}
