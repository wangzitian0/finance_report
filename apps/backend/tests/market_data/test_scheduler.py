"""AC11.10: Market data scheduler tests."""

import asyncio
from datetime import datetime
from unittest.mock import Mock

import pytest

from src.pricing import MarketDataSyncResult
from src.services import market_data_scheduler
from src.services.market_data_scheduler import MARKET_DATA_SYNC_TZ, next_market_data_sync_at


def test_next_market_data_sync_at_uses_nightly_sgt_schedule() -> None:
    """AC-pricing.marketdata.10: AC11.10.10: Nightly sync is scheduled for 22:00 Asia/Singapore."""
    before = datetime(2026, 1, 6, 21, 0, tzinfo=MARKET_DATA_SYNC_TZ)
    after = datetime(2026, 1, 6, 23, 0, tzinfo=MARKET_DATA_SYNC_TZ)

    assert next_market_data_sync_at(before) == datetime(2026, 1, 6, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ)
    assert next_market_data_sync_at(after) == datetime(2026, 1, 7, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ)


async def test_run_daily_market_data_sync_uses_sessionmaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.10: Daily sync opens a DB session and runs FX then stock sync."""

    class FakeSession:
        committed = False

        async def commit(self) -> None:
            self.committed = True

    session = FakeSession()
    calls: list[tuple[str, object]] = []

    class FakeSessionMaker:
        def __call__(self) -> "FakeSessionMaker":
            return self

        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def fake_fx(db: object, *, pairs: object) -> MarketDataSyncResult:
        calls.append(("fx", db))
        return MarketDataSyncResult(kind="fx", requested=1, inserted=1)

    async def fake_stock(db: object, *, symbols: object) -> MarketDataSyncResult:
        calls.append(("stock", db))
        return MarketDataSyncResult(kind="stock", requested=1, inserted=1)

    async def fake_observed_fx_pairs(db: object, user_id: object) -> list[str]:
        return []

    async def fake_active_stock_symbols(db: object, user_id: object) -> list[str]:
        return []

    monkeypatch.setattr(market_data_scheduler, "observed_fx_pairs", fake_observed_fx_pairs)
    monkeypatch.setattr(market_data_scheduler, "active_stock_symbols", fake_active_stock_symbols)
    monkeypatch.setattr(market_data_scheduler, "sync_fx_rates", fake_fx)
    monkeypatch.setattr(market_data_scheduler, "sync_stock_prices", fake_stock)

    await market_data_scheduler.run_daily_market_data_sync(sessionmaker=FakeSessionMaker())  # type: ignore[arg-type]

    assert calls == [("fx", session), ("stock", session)]
    assert session.committed is True


async def test_run_market_data_scheduler_runs_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.10: Scheduler runs daily sync when the wait reaches the nightly window."""
    stop_event = asyncio.Event()
    calls = 0

    async def fake_wait_for(awaitable: object, *, timeout: float) -> None:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        assert timeout >= 0
        raise TimeoutError

    async def fake_daily_sync(*, sessionmaker: object | None = None) -> None:
        nonlocal calls
        assert sessionmaker is None
        calls += 1
        stop_event.set()

    monkeypatch.setattr(market_data_scheduler.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(market_data_scheduler, "run_daily_market_data_sync", fake_daily_sync)

    await market_data_scheduler.run_market_data_scheduler(stop_event)

    assert calls == 1


async def test_run_market_data_scheduler_exits_if_stopped_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC11.10.10: Scheduler exits cleanly if stopped before the sync starts."""
    stop_event = asyncio.Event()

    async def fake_wait_for(awaitable: object, *, timeout: float) -> None:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        stop_event.set()
        raise TimeoutError

    daily_sync = Mock()
    monkeypatch.setattr(market_data_scheduler.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(market_data_scheduler, "run_daily_market_data_sync", daily_sync)

    await market_data_scheduler.run_market_data_scheduler(stop_event)

    daily_sync.assert_not_called()


async def test_run_market_data_scheduler_logs_and_continues_after_sync_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11.10.10: Scheduler catches one failed daily sync and exits on the next stop signal."""
    stop_event = asyncio.Event()
    waits = 0

    async def fake_wait_for(awaitable: object, *, timeout: float) -> None:
        nonlocal waits
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        waits += 1
        if waits == 1:
            raise TimeoutError
        stop_event.set()
        return None

    async def fake_daily_sync(*, sessionmaker: object | None = None) -> None:
        assert sessionmaker is None
        raise RuntimeError("provider down")

    monkeypatch.setattr(market_data_scheduler.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(market_data_scheduler, "run_daily_market_data_sync", fake_daily_sync)

    await market_data_scheduler.run_market_data_scheduler(stop_event)

    assert waits == 2
