"""The daily market-data crawl orchestrator (absorbed from
``services/market_data_scheduler.py``, #1610 P2).

Pricing never discovers *which* scopes to sync — deciding that requires
reading ledger/portfolio/extraction data, and pricing is an L3 leaf (it
imports no other domain package). The composition root composes the three
per-domain published reads into a :class:`MarketDataScopes` provider
(``src/composition.py::market_data_scopes``) and injects it here — the same
call-convention inversion as the sync services themselves taking explicit
``pairs``/``symbols`` (meta Decision B, #1641; AC-pricing.marketdata.12).

The one ``session.commit()`` per run finalizes only pricing's own aggregates
(``fx_rates``/``stock_prices``/``market_data_sync_state`` rows written by
``sync_fx_rates``/``sync_stock_prices``) — the injected provider performs
reads only. The commit is a documented transaction boundary, guarded by
``tests/infra/test_transaction_boundaries.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database import async_session_maker
from src.observability import get_logger
from src.pricing.extension.market_data import (
    MarketDataSyncResult,
    fetch_planned_fx_sync,
    fetch_planned_stock_sync,
    persist_fetched_fx_sync,
    persist_fetched_stock_sync,
    plan_fx_sync,
    plan_stock_sync,
)

logger = get_logger(__name__)

MARKET_DATA_SYNC_TZ = ZoneInfo("Asia/Singapore")
MARKET_DATA_DAILY_SYNC_TIME = time(hour=22, minute=0)


@dataclass(frozen=True)
class MarketDataScopes:
    """The crawl scopes one daily sync run covers.

    Produced by the composition root's provider (which composes the
    per-domain published reads); consumed verbatim by
    :func:`run_daily_market_data_sync`.
    """

    fx_pairs: list[str] = field(default_factory=list)
    stock_symbols: list[str] = field(default_factory=list)


#: The port the composition root implements: given a session, return the
#: scopes to sync (reads only — the scheduler owns the single commit).
MarketDataScopeProvider = Callable[[AsyncSession], Awaitable[MarketDataScopes]]


def next_market_data_sync_at(now: datetime) -> datetime:
    """Return the next 22:00 SGT market data sync time after ``now``."""
    localized = now.astimezone(MARKET_DATA_SYNC_TZ)
    candidate = datetime.combine(localized.date(), MARKET_DATA_DAILY_SYNC_TIME, tzinfo=MARKET_DATA_SYNC_TZ)
    if candidate <= localized:
        candidate += timedelta(days=1)
    return candidate


async def run_daily_market_data_sync(
    scopes: MarketDataScopeProvider,
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Run one daily incremental market data sync for the provided scopes."""
    session_factory = sessionmaker or async_session_maker
    async with session_factory() as read_session:
        run_scopes = await scopes(read_session)
        fx_plan = await plan_fx_sync(read_session, pairs=run_scopes.fx_pairs)
        stock_plan = await plan_stock_sync(read_session, symbols=run_scopes.stock_symbols)

    if fx_plan.has_work or stock_plan.has_work:
        fx_fetched, stock_fetched = await asyncio.gather(
            fetch_planned_fx_sync(fx_plan),
            fetch_planned_stock_sync(stock_plan),
        )
        async with session_factory() as write_session:
            fx_result = await persist_fetched_fx_sync(write_session, fx_plan, fx_fetched)
            stock_result = await persist_fetched_stock_sync(write_session, stock_plan, stock_fetched)
            await write_session.commit()
    else:
        fx_result = MarketDataSyncResult(kind="fx", skipped=fx_plan.skipped)
        stock_result = MarketDataSyncResult(kind="stock", skipped=stock_plan.skipped)
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
    scopes: MarketDataScopeProvider,
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
            await run_daily_market_data_sync(scopes, sessionmaker=sessionmaker)
        except Exception:
            logger.exception("Daily market data sync failed")
