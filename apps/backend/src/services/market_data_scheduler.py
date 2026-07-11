"""Background scheduler for daily market data sync — plus the FX-scope composer.

``observed_fx_pairs`` is the thin delivery-layer composer that replaced the
old ``services/market_data_discovery.py`` glue (#1641): each domain publishes
its own currencies read (``ledger.used_currencies``,
``portfolio.position_currencies``, ``extraction.snapshot_currencies``) and
this composer merges them with the configured base/default-counterparty
currencies into the ``<currency>/<base>`` pairs passed to ``pricing``'s crawl
(call-convention inversion — pricing never discovers scopes itself). It lives
here, not in any domain package, because it is cross-domain composition;
#1610 absorbs this module next.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.audit import normalize_currency_code
from src.config import settings
from src.database import async_session_maker
from src.extraction import snapshot_currencies
from src.ledger import used_currencies
from src.observability import get_logger
from src.portfolio import active_stock_symbols, position_currencies
from src.pricing import sync_fx_rates, sync_stock_prices

logger = get_logger(__name__)

MARKET_DATA_SYNC_TZ = ZoneInfo("Asia/Singapore")
MARKET_DATA_DAILY_SYNC_TIME = time(hour=22, minute=0)


async def observed_fx_pairs(
    db: AsyncSession,
    user_id: UUID | None,
    *,
    include_default: bool = True,
) -> list[str]:
    """The ``<currency>/<base>`` pairs implied by every currency the user holds."""
    base = normalize_currency_code(settings.base_currency)
    default_counterparty = "USD" if base != "USD" else "SGD"
    currencies: set[str] = {base}
    if include_default:
        currencies.add(default_counterparty)

    currencies |= await used_currencies(db, user_id)
    currencies |= await position_currencies(db, user_id)
    currencies |= await snapshot_currencies(db, user_id)

    return [f"{currency}/{base}" for currency in sorted(currencies) if currency != base]


def next_market_data_sync_at(now: datetime) -> datetime:
    """Return the next 22:00 SGT market data sync time after ``now``."""
    localized = now.astimezone(MARKET_DATA_SYNC_TZ)
    candidate = datetime.combine(localized.date(), MARKET_DATA_DAILY_SYNC_TIME, tzinfo=MARKET_DATA_SYNC_TZ)
    if candidate <= localized:
        candidate += timedelta(days=1)
    return candidate


async def run_daily_market_data_sync(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Run one daily incremental market data sync for all observed scopes."""
    session_factory = sessionmaker or async_session_maker
    async with session_factory() as session:
        fx_pairs = await observed_fx_pairs(session, None)
        stock_symbols = await active_stock_symbols(session, None)
        fx_result = await sync_fx_rates(session, pairs=fx_pairs)
        stock_result = await sync_stock_prices(session, symbols=stock_symbols)
        await session.commit()
    logger.info(
        "Daily market data sync completed",
        fx_requested=fx_result.requested,
        fx_inserted=fx_result.inserted,
        fx_missing=fx_result.missing,
        stock_requested=stock_result.requested,
        stock_inserted=stock_result.inserted,
        stock_missing=stock_result.missing,
        fx_disagreements=len(fx_result.disagreements),
        stock_disagreements=len(stock_result.disagreements),
    )


async def run_market_data_scheduler(
    stop_event: asyncio.Event,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Run the daily market data sync until ``stop_event`` is set."""
    while not stop_event.is_set():
        now = datetime.now(MARKET_DATA_SYNC_TZ)
        next_run = next_market_data_sync_at(now)
        wait_seconds = max((next_run - now).total_seconds(), 0)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
            continue
        except TimeoutError:
            pass

        if stop_event.is_set():
            break

        try:
            await run_daily_market_data_sync(sessionmaker=sessionmaker)
        except Exception:
            logger.exception("Daily market data sync failed")
