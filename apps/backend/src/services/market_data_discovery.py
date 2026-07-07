"""App-glue: discover which FX pairs / stock symbols the user's holdings need.

This is the **ledger-reading** half of market-data sync — it inspects the user's
accounts, journal, and positions to decide *which* scopes to crawl. It stays in
the app layer on purpose: it reads ledger/portfolio models (``Account``,
``JournalLine``, ``AtomicPosition``, ``ManagedPosition``), so it must NOT live
inside the ``pricing`` package (pricing depends on ``audit``/``platform`` only,
never on the domain flow). The pure crawl — *given* a set of scopes, fetch and
store observations — is pricing's; this module is the boundary that feeds it
(dependency inversion, meta Decision B): the caller (scheduler / router)
discovers the scopes here and passes them to pricing's crawl.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.quantity import Quantity
from src.config import settings
from src.models.account import Account
from src.models.journal import JournalEntry, JournalLine
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.services.market_data._base import MARKET_DATA_QUANTITY_UNIT
from src.services.market_data._util import _normalize_currency, _normalize_symbol


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
    return sorted({_normalize_symbol(row[0]) for row in result.all() if row[0]})


async def observed_fx_pairs(
    db: AsyncSession,
    user_id: UUID | None,
    *,
    include_default: bool = True,
) -> list[str]:
    """The ``<currency>/<base>`` pairs implied by every currency the user holds."""
    base = _normalize_currency(settings.base_currency)
    default_counterparty = "USD" if base != "USD" else "SGD"
    currencies: set[str] = {base}
    if include_default:
        currencies.add(default_counterparty)

    account_stmt = select(Account.currency)
    if user_id is not None:
        account_stmt = account_stmt.where(Account.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(account_stmt)).all() if row[0])

    line_stmt = select(JournalLine.currency).join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
    if user_id is not None:
        line_stmt = line_stmt.where(JournalEntry.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(line_stmt)).all() if row[0])

    position_stmt = select(ManagedPosition.currency)
    if user_id is not None:
        position_stmt = position_stmt.where(ManagedPosition.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(position_stmt)).all() if row[0])

    snapshot_stmt = select(AtomicPosition.currency)
    if user_id is not None:
        snapshot_stmt = snapshot_stmt.where(AtomicPosition.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(snapshot_stmt)).all() if row[0])

    return [f"{currency}/{base}" for currency in sorted(currencies) if currency != base]
