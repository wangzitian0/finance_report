from __future__ import annotations; from uuid import uuid4; import pytest; from src.extraction.extension import brokerage_positions; from src.portfolio.extension.holdings import _account_names_by_id; from src.routers.reconciliation import _load_transactions
class _ExplodingSession:
    def __getattr__(self, name: str) -> None: raise AssertionError(f'empty-input guard must not touch the session (accessed .{name})')
async def test_brokerage_reconciler_port_fails_fast_when_unwired() -> None:
    service = brokerage_positions.BrokeragePositionImportService()
    payload = {'institution': 'Interactive Brokers', 'statement': {'period_end': '2026-05-18', 'currency': 'USD'}, 'positions': [{'symbol': 'AAPL', 'quantity': '10', 'market_value': '100.00', 'currency': 'USD'}]}
    with pytest.raises(RuntimeError, match='position_reconciler'):
        await service.import_positions(_ExplodingSession(), user_id=uuid4(), payload=payload)
async def test_account_names_lookup_short_circuits_on_no_ids() -> None: assert await _account_names_by_id(_ExplodingSession(), uuid4(), set()) == {}; assert await _load_transactions(_ExplodingSession(), []) == {}; assert await _load_transactions(_ExplodingSession(), [], uuid4()) == {}
