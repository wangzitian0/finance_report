"""Reconciliation test fixtures for the EPIC-011 PR-B read cutover.

`ENABLE_4_LAYER_READ` now defaults to True, so `execute_matching` reads Layer 2
(`atomic_transactions`) and resolves the transfer custody account from the
`StatementSummary` conform. Most reconciliation tests still seed Layer 0 fixtures
(BankStatement + BankStatementTransaction) directly.

This autouse fixture projects those Layer 0 fixtures into Layer 2 + the conform
(the exact projection production gets from Stage 1 dual-write + Stage 2a backfill
+ the PR-A StatementSummary sync) immediately before the engine reads them, so
existing fixtures exercise the real activated read path without rewriting every
test body.

Removed in Stage 3, when reconciliation fixtures are rebuilt natively on Layer 2
and the legacy `bank_statement*` tables are deprecated.
"""

import pytest


@pytest.fixture(autouse=True)
def bridge_layer0_recon_fixtures_into_layer2(monkeypatch):
    from src.services import reconciliation as recon
    from src.services.deduplication import backfill_atomic_transactions_from_statements

    original = recon._get_pending_layer2_transactions

    async def _backfilled_pending(db, user_id, limit=None):
        # Projects Layer 0 -> atomic_transactions AND StatementSummary (custody account).
        await backfill_atomic_transactions_from_statements(db, user_id=user_id)
        return await original(db, user_id, limit=limit)

    monkeypatch.setattr(recon, "_get_pending_layer2_transactions", _backfilled_pending)
    yield
