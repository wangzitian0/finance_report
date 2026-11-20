from __future__ import annotations

import ast
import asyncio
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.pricing import (
    MARKET_DATA_SYNC_TZ,
    FetchedMarketSync,
    MarketDataScopes,
    MarketDataSyncResult,
    PlannedMarketSync,
    PlannedScopeSync,
    next_market_data_sync_at,
)
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
    created_sessions: list[object] = []
    active_sessions = 0
    calls: list[tuple[str, object, object]] = []
    fetch_active_sessions: list[int] = []
    provider_sessions: list[object] = []

    class FakeSession:
        def __init__(self) -> None:
            self.committed = False

        async def commit(self) -> None:
            self.committed = True

    class FakeSessionCtx:
        def __init__(self) -> None:
            self.session = FakeSession()

        async def __aenter__(self):
            nonlocal active_sessions
            active_sessions += 1
            created_sessions.append(self.session)
            return self.session

        async def __aexit__(self, *_a):
            nonlocal active_sessions
            active_sessions -= 1
            return None

    class FakeSessionMaker:
        def __call__(self):
            return FakeSessionCtx()

    async def fake_plan_fx(db, *, pairs):
        calls.append(("plan_fx", db, pairs))
        return PlannedMarketSync(
            kind="fx",
            end_date=date(2026, 1, 6),
            skipped=0,
            items=(PlannedScopeSync(scope=("USD", "SGD"), scope_name="USD/SGD", last_date=None, requested_dates=frozenset({date(2026, 1, 6)})),),
        )

    async def fake_plan_stock(db, *, symbols):
        calls.append(("plan_stock", db, symbols))
        return PlannedMarketSync(
            kind="stock",
            end_date=date(2026, 1, 6),
            skipped=0,
            items=(PlannedScopeSync(scope="AAPL", scope_name="AAPL", last_date=None, requested_dates=frozenset({date(2026, 1, 6)})),),
        )

    async def fake_fetch_fx(plan):
        fetch_active_sessions.append(active_sessions)
        calls.append(("fetch_fx", active_sessions, plan.kind))
        return FetchedMarketSync(kind="fx", items=())

    async def fake_fetch_stock(plan):
        fetch_active_sessions.append(active_sessions)
        calls.append(("fetch_stock", active_sessions, plan.kind))
        return FetchedMarketSync(kind="stock", items=())

    async def fake_persist_fx(db, _plan, _fetched):
        calls.append(("persist_fx", db, None))
        return MarketDataSyncResult(kind="fx", requested=1, inserted=1)

    async def fake_persist_stock(db, _plan, _fetched):
        calls.append(("persist_stock", db, None))
        return MarketDataSyncResult(kind="stock", requested=1, inserted=1)

    async def scopes(db):
        provider_sessions.append(db)
        return MarketDataScopes(fx_pairs=["USD/SGD"], stock_symbols=["AAPL"])

    monkeypatch.setattr(scheduler_module, "plan_fx_sync", fake_plan_fx)
    monkeypatch.setattr(scheduler_module, "plan_stock_sync", fake_plan_stock)
    monkeypatch.setattr(scheduler_module, "fetch_planned_fx_sync", fake_fetch_fx)
    monkeypatch.setattr(scheduler_module, "fetch_planned_stock_sync", fake_fetch_stock)
    monkeypatch.setattr(scheduler_module, "persist_fetched_fx_sync", fake_persist_fx)
    monkeypatch.setattr(scheduler_module, "persist_fetched_stock_sync", fake_persist_stock)
    await scheduler_module.run_daily_market_data_sync(scopes, sessionmaker=FakeSessionMaker())

    assert len(created_sessions) == 2
    read_session, write_session = created_sessions
    assert (provider_sessions, read_session.committed, write_session.committed, fetch_active_sessions) == (
        [read_session],
        False,
        True,
        [0, 0],
    )
    assert calls == [
        ("plan_fx", read_session, ["USD/SGD"]),
        ("plan_stock", read_session, ["AAPL"]),
        ("fetch_fx", 0, "fx"),
        ("fetch_stock", 0, "stock"),
        ("persist_fx", write_session, None),
        ("persist_stock", write_session, None),
    ]


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
