"""AC-pricing.marketdata.10/.12: the daily market-data crawl orchestrator.

Moved from ``tests/market_data/test_scheduler.py`` when #1610 P2 absorbed
``services/market_data_scheduler.py`` into ``pricing/extension/scheduler.py``.
The scheduler never discovers *which* scopes to sync itself — the composition
root injects a scope provider (dependency inversion, #1641/#1610): pricing is
an L3 leaf and must not read ledger/portfolio/extraction data.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.pricing import (
    MARKET_DATA_SYNC_TZ,
    MarketDataScopes,
    MarketDataSyncResult,
    next_market_data_sync_at,
)
from src.pricing.extension import scheduler as scheduler_module


async def _static_scopes(_db: object) -> MarketDataScopes:
    return MarketDataScopes(fx_pairs=["USD/SGD"], stock_symbols=["AAPL"])


def test_next_market_data_sync_at_uses_nightly_sgt_schedule() -> None:
    """AC-pricing.marketdata.10: AC11.10.10: Nightly sync is scheduled for 22:00 Asia/Singapore."""
    before = datetime(2026, 1, 6, 21, 0, tzinfo=MARKET_DATA_SYNC_TZ)
    after = datetime(2026, 1, 6, 23, 0, tzinfo=MARKET_DATA_SYNC_TZ)

    assert next_market_data_sync_at(before) == datetime(2026, 1, 6, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ)
    assert next_market_data_sync_at(after) == datetime(2026, 1, 7, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ)


async def test_AC_pricing_marketdata_12_daily_sync_uses_injected_scope_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.12: the daily sync syncs exactly the scopes the
    injected provider returns (pricing never discovers scopes itself) and
    commits once at the end."""

    class FakeSession:
        committed = False

        async def commit(self) -> None:
            self.committed = True

    session = FakeSession()
    calls: list[tuple[str, object, object]] = []

    class FakeSessionMaker:
        def __call__(self) -> FakeSessionMaker:
            return self

        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def fake_fx(db: object, *, pairs: object) -> MarketDataSyncResult:
        calls.append(("fx", db, pairs))
        return MarketDataSyncResult(kind="fx", requested=1, inserted=1)

    async def fake_stock(db: object, *, symbols: object) -> MarketDataSyncResult:
        calls.append(("stock", db, symbols))
        return MarketDataSyncResult(kind="stock", requested=1, inserted=1)

    provider_sessions: list[object] = []

    async def scopes(db: object) -> MarketDataScopes:
        provider_sessions.append(db)
        return MarketDataScopes(fx_pairs=["USD/SGD"], stock_symbols=["AAPL"])

    monkeypatch.setattr(scheduler_module, "sync_fx_rates", fake_fx)
    monkeypatch.setattr(scheduler_module, "sync_stock_prices", fake_stock)

    await scheduler_module.run_daily_market_data_sync(scopes, sessionmaker=FakeSessionMaker())  # type: ignore[arg-type]

    assert provider_sessions == [session]
    assert calls == [("fx", session, ["USD/SGD"]), ("stock", session, ["AAPL"])]
    assert session.committed is True


def test_AC_pricing_marketdata_12_scheduler_module_imports_no_other_domain() -> None:
    """AC-pricing.marketdata.12: the scheduler module keeps pricing an L3 leaf —
    it imports no other domain package and nothing from the app remainder
    (the scope composer lives at the composition root instead)."""
    scheduler_path = Path(scheduler_module.__file__)
    tree = ast.parse(scheduler_path.read_text(encoding="utf-8"))

    forbidden_prefixes = (
        "src.extraction",
        "src.ledger",
        "src.portfolio",
        "src.reconciliation",
        "src.reporting",
        "src.services",
        "src.routers",
    )
    offending: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        offending.extend(m for m in modules if m.startswith(forbidden_prefixes))

    assert offending == []


async def test_run_market_data_scheduler_runs_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-pricing.marketdata.10: Scheduler runs daily sync when the wait reaches the nightly window."""
    stop_event = asyncio.Event()
    calls = 0

    async def fake_wait_for(awaitable: object, *, timeout: float) -> None:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        assert timeout >= 0
        raise TimeoutError

    async def fake_daily_sync(scopes: object, *, sessionmaker: object | None = None) -> None:
        nonlocal calls
        assert scopes is _static_scopes
        assert sessionmaker is None
        calls += 1
        stop_event.set()

    monkeypatch.setattr(scheduler_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(scheduler_module, "run_daily_market_data_sync", fake_daily_sync)

    await scheduler_module.run_market_data_scheduler(stop_event, _static_scopes)

    assert calls == 1


async def test_run_market_data_scheduler_exits_if_stopped_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-pricing.marketdata.10: Scheduler exits cleanly if stopped before the sync starts."""
    stop_event = asyncio.Event()

    async def fake_wait_for(awaitable: object, *, timeout: float) -> None:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        stop_event.set()
        raise TimeoutError

    daily_sync = Mock()
    monkeypatch.setattr(scheduler_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(scheduler_module, "run_daily_market_data_sync", daily_sync)

    await scheduler_module.run_market_data_scheduler(stop_event, _static_scopes)

    daily_sync.assert_not_called()


async def test_run_market_data_scheduler_logs_and_continues_after_sync_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-pricing.marketdata.10: Scheduler catches one failed daily sync and exits on the next stop signal."""
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

    async def fake_daily_sync(scopes: object, *, sessionmaker: object | None = None) -> None:
        assert scopes is _static_scopes
        assert sessionmaker is None
        raise RuntimeError("provider down")

    monkeypatch.setattr(scheduler_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(scheduler_module, "run_daily_market_data_sync", fake_daily_sync)

    await scheduler_module.run_market_data_scheduler(stop_event, _static_scopes)

    assert waits == 2
