from __future__ import annotations

import ast
import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.pricing import MARKET_DATA_SYNC_TZ, MarketDataScopes, MarketDataSyncResult, next_market_data_sync_at
from src.pricing.extension import scheduler as scheduler_module


async def _static_scopes(_db: object) -> MarketDataScopes:
    return MarketDataScopes(fx_pairs=["USD/SGD"], stock_symbols=["AAPL"])


def test_next_market_data_sync_at_and_no_forbidden_imports() -> None:
    before, after = datetime(2026, 1, 6, 21, 0, tzinfo=MARKET_DATA_SYNC_TZ), datetime(2026, 1, 6, 23, 0, tzinfo=MARKET_DATA_SYNC_TZ)
    tree = ast.parse(Path(scheduler_module.__file__).read_text(encoding="utf-8"))
    forbidden = ("src.extraction", "src.ledger", "src.portfolio", "src.reconciliation", "src.reporting", "src.services", "src.routers")
    imported = [
        mod
        for node in ast.walk(tree)
        for mod in ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
        if mod.startswith(forbidden)
    ]
    assert (next_market_data_sync_at(before), next_market_data_sync_at(after), imported) == (datetime(2026, 1, 6, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ), datetime(2026, 1, 7, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ), [])


async def test_AC_pricing_marketdata_12_daily_sync_uses_injected_scope_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    session = type("_Session", (), {"committed": False, "commit": lambda self: _set_commit(self)})()
    calls: list[tuple[str, object, object]] = []
    provider_sessions: list[object] = []

    class FakeSessionMaker:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *_a):
            return None

    async def _set_commit(s):
        s.committed = True

    async def fake_fx(db, *, pairs):
        calls.append(("fx", db, pairs))
        return MarketDataSyncResult(kind="fx", requested=1, inserted=1)

    async def fake_stock(db, *, symbols):
        calls.append(("stock", db, symbols))
        return MarketDataSyncResult(kind="stock", requested=1, inserted=1)

    async def scopes(db):
        provider_sessions.append(db)
        return MarketDataScopes(fx_pairs=["USD/SGD"], stock_symbols=["AAPL"])

    monkeypatch.setattr(scheduler_module, "sync_fx_rates", fake_fx)
    monkeypatch.setattr(scheduler_module, "sync_stock_prices", fake_stock)
    await scheduler_module.run_daily_market_data_sync(scopes, sessionmaker=FakeSessionMaker())
    assert (provider_sessions, calls, session.committed) == ([session], [("fx", session, ["USD/SGD"]), ("stock", session, ["AAPL"])], True)


@pytest.mark.parametrize("mode", ["runs_after_timeout", "exits_when_stopped", "continues_after_error"])
async def test_run_market_data_scheduler_loop(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    stop_event = asyncio.Event()
    waits = calls = 0

    async def fake_wait_for(awaitable: object, *, timeout: float) -> None:
        nonlocal waits
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        waits += 1
        assert timeout >= 0
        if mode == "exits_when_stopped":
            stop_event.set()
            raise TimeoutError
        if mode == "runs_after_timeout" or waits == 1:
            raise TimeoutError
        stop_event.set()

    async def fake_daily_sync(scopes, *, sessionmaker=None):
        nonlocal calls
        assert (scopes is _static_scopes, sessionmaker is None) == (True, True)
        calls += 1
        if mode == "continues_after_error":
            raise RuntimeError("provider down")
        stop_event.set()

    daily_sync = Mock() if mode == "exits_when_stopped" else fake_daily_sync
    monkeypatch.setattr(scheduler_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(scheduler_module, "run_daily_market_data_sync", daily_sync)
    await scheduler_module.run_market_data_scheduler(stop_event, _static_scopes)
    if mode == "exits_when_stopped":
        daily_sync.assert_not_called()
    else:
        assert (calls, waits) == (1, 1 if mode == "runs_after_timeout" else 2)
