"""#1675 D4/D5c de-navigation seams — fail-fast ports and empty-input guards.

The cross-domain ``relationship()`` removals introduced two seam shapes that
never fire on the happy path and so are easy to leave unproven:

* provider ports (``register_*`` wired by ``main.py`` at startup) must raise
  a self-diagnosing ``RuntimeError`` when a caller reaches them unwired, and
* the explicit batch-fetch helpers that replaced eager-loads must return
  empty without touching the session when given nothing to fetch.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.extraction.extension import brokerage_positions, review_queue
from src.ledger.extension import fx_revaluation
from src.portfolio.extension.holdings import _account_names_by_id
from src.routers.reconciliation import _load_transactions


class _ExplodingSession:
    """A session stand-in that fails the test if the guard ever queries it."""

    def __getattr__(self, name: str) -> None:
        raise AssertionError(f"empty-input guard must not touch the session (accessed .{name})")


def test_review_queue_fx_port_fails_fast_when_unwired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_queue, "_get_exchange_rate", None)
    with pytest.raises(RuntimeError, match="register_fx_rate_provider"):
        review_queue._require_fx_rate_provider()


def test_brokerage_reconciler_port_fails_fast_when_unwired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brokerage_positions, "_position_reconciler", None)
    with pytest.raises(RuntimeError, match="register_position_reconciler"):
        brokerage_positions._get_position_reconciler()


def test_fx_revaluation_port_fails_fast_when_unwired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx_revaluation, "_get_exchange_rate", None)
    with pytest.raises(RuntimeError, match="register_fx_revaluation_provider"):
        fx_revaluation._require_fx_rate_provider()


@pytest.mark.asyncio
async def test_account_names_lookup_short_circuits_on_no_ids() -> None:
    assert await _account_names_by_id(_ExplodingSession(), uuid4(), set()) == {}


@pytest.mark.asyncio
async def test_match_transaction_fetch_short_circuits_on_no_matches() -> None:
    assert await _load_transactions(_ExplodingSession(), []) == {}
