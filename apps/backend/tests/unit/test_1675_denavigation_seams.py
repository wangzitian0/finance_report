from __future__ import annotations; from uuid import uuid4; import pytest; from src.extraction.extension import brokerage_positions; from src.portfolio.extension.holdings import _account_names_by_id; from src.routers.reconciliation import _load_transactions
class _ExplodingSession:
    def __getattr__(self, name: str) -> None: raise AssertionError(f'empty-input guard must not touch the session (accessed .{name})')
def test_brokerage_reconciler_port_fails_fast_when_unwired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brokerage_positions, '_position_reconciler', None)
    with pytest.raises(RuntimeError, match='register_position_reconciler'): brokerage_positions._get_position_reconciler()
async def test_account_names_lookup_short_circuits_on_no_ids() -> None: assert await _account_names_by_id(_ExplodingSession(), uuid4(), set()) == {}; assert await _load_transactions(_ExplodingSession(), []) == {}; assert await _load_transactions(_ExplodingSession(), [], uuid4()) == {}
