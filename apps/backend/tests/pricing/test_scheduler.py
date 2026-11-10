'AC-pricing.marketdata.10'; from __future__ import annotations; import ast; import asyncio; from datetime import datetime; from pathlib import Path; from unittest.mock import Mock; import pytest; from src.pricing import MARKET_DATA_SYNC_TZ, MarketDataScopes, MarketDataSyncResult, next_market_data_sync_at; from src.pricing.extension import scheduler as scheduler_module
async def _static_scopes(_db: object) -> MarketDataScopes: return MarketDataScopes(fx_pairs=['USD/SGD'], stock_symbols=['AAPL'])
def test_next_market_data_sync_at_uses_nightly_sgt_schedule() -> None:
    'AC-pricing.marketdata.10 AC11.10.10'; before = datetime(2026, 1, 6, 21, 0, tzinfo=MARKET_DATA_SYNC_TZ); after = datetime(2026, 1, 6, 23, 0, tzinfo=MARKET_DATA_SYNC_TZ); assert next_market_data_sync_at(before) == datetime(2026, 1, 6, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ); assert next_market_data_sync_at(after) == datetime(2026, 1, 7, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ); 'AC-pricing.marketdata.12'; 'AC-pricing.marketdata.12'; _m1_scheduler_path = Path(scheduler_module.__file__); _m1_tree = ast.parse(_m1_scheduler_path.read_text(encoding='utf-8')); _m1_forbidden_prefixes = ('src.extraction', 'src.ledger', 'src.portfolio', 'src.reconciliation', 'src.reporting', 'src.services', 'src.routers'); _m1_offending: list[str] = []
    for _m1_node in ast.walk(_m1_tree): _m1_modules: list[str] = []; _m1_modules.append(_m1_node.module) if isinstance(_m1_node, ast.ImportFrom) and _m1_node.module else _m1_modules.extend((_m1_alias.name for _m1_alias in _m1_node.names)) if isinstance(_m1_node, ast.Import) else None; _m1_offending.extend((_m1_m for _m1_m in _m1_modules if _m1_m.startswith(_m1_forbidden_prefixes)))
    assert _m1_offending == []
async def test_AC_pricing_marketdata_12_daily_sync_uses_injected_scope_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-pricing.marketdata.12'
    class FakeSession:
        committed = False
        async def commit(self) -> None: self.committed = True
    session = FakeSession(); calls: list[tuple[str, object, object]] = []
    class FakeSessionMaker:
        def __call__(self) -> FakeSessionMaker: return self
        async def __aenter__(self) -> object: return session
        async def __aexit__(self, *_args: object) -> None: return None
    async def fake_fx(db: object, *, pairs: object) -> MarketDataSyncResult: calls.append(('fx', db, pairs)); return MarketDataSyncResult(kind='fx', requested=1, inserted=1)
    async def fake_stock(db: object, *, symbols: object) -> MarketDataSyncResult: calls.append(('stock', db, symbols)); return MarketDataSyncResult(kind='stock', requested=1, inserted=1)
    provider_sessions: list[object] = []
    async def scopes(db: object) -> MarketDataScopes: provider_sessions.append(db); return MarketDataScopes(fx_pairs=['USD/SGD'], stock_symbols=['AAPL'])
    monkeypatch.setattr(scheduler_module, 'sync_fx_rates', fake_fx); monkeypatch.setattr(scheduler_module, 'sync_stock_prices', fake_stock); await scheduler_module.run_daily_market_data_sync(scopes, sessionmaker=FakeSessionMaker()); assert provider_sessions == [session]; assert calls == [('fx', session, ['USD/SGD']), ('stock', session, ['AAPL'])]; assert session.committed is True
async def test_run_market_data_scheduler_runs_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-pricing.marketdata.10'; stop_event = asyncio.Event(); calls = 0
    async def fake_wait_for(awaitable: object, *, timeout: float) -> None: close = getattr(awaitable, 'close', None); close() if close is not None else None; assert timeout >= 0; raise TimeoutError
    async def fake_daily_sync(scopes: object, *, sessionmaker: object | None=None) -> None: nonlocal calls; assert scopes is _static_scopes; assert sessionmaker is None; calls += 1; stop_event.set()
    monkeypatch.setattr(scheduler_module.asyncio, 'wait_for', fake_wait_for); monkeypatch.setattr(scheduler_module, 'run_daily_market_data_sync', fake_daily_sync); await scheduler_module.run_market_data_scheduler(stop_event, _static_scopes); assert calls == 1
async def test_run_market_data_scheduler_exits_if_stopped_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-pricing.marketdata.10'; stop_event = asyncio.Event()
    async def fake_wait_for(awaitable: object, *, timeout: float) -> None: close = getattr(awaitable, 'close', None); close() if close is not None else None; stop_event.set(); raise TimeoutError
    daily_sync = Mock(); monkeypatch.setattr(scheduler_module.asyncio, 'wait_for', fake_wait_for); monkeypatch.setattr(scheduler_module, 'run_daily_market_data_sync', daily_sync); await scheduler_module.run_market_data_scheduler(stop_event, _static_scopes); daily_sync.assert_not_called()
async def test_run_market_data_scheduler_logs_and_continues_after_sync_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    'AC-pricing.marketdata.10'; stop_event = asyncio.Event(); waits = 0
    async def fake_wait_for(awaitable: object, *, timeout: float) -> None:
        nonlocal waits; close = getattr(awaitable, 'close', None); close() if close is not None else None; waits += 1
        if waits == 1: raise TimeoutError
        stop_event.set(); return None
    async def fake_daily_sync(scopes: object, *, sessionmaker: object | None=None) -> None: assert scopes is _static_scopes; assert sessionmaker is None; raise RuntimeError('provider down')
    monkeypatch.setattr(scheduler_module.asyncio, 'wait_for', fake_wait_for); monkeypatch.setattr(scheduler_module, 'run_daily_market_data_sync', fake_daily_sync); await scheduler_module.run_market_data_scheduler(stop_event, _static_scopes); assert waits == 2
