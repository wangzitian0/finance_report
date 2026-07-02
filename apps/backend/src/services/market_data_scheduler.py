"""Background scheduler for daily market data sync."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database import async_session_maker
from src.observability import get_logger
from src.services.market_data import sync_fx_rates, sync_stock_prices

logger = get_logger(__name__)

MARKET_DATA_SYNC_TZ = ZoneInfo("Asia/Singapore")
MARKET_DATA_DAILY_SYNC_TIME = time(hour=22, minute=0)


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
        fx_result = await sync_fx_rates(session)
        stock_result = await sync_stock_prices(session)
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
