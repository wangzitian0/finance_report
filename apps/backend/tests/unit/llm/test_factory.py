"""Factory wiring: the budget meter must be a shared singleton (EPIC-023 PR5).

A fresh ``DailyBudgetMeter`` per ``get_llm_client()`` would reset ``spent_today``
to zero every call, so the daily limit would never be enforced. ``get_budget_meter``
must hand back one shared instance.
"""

from __future__ import annotations

import src.llm.factory as factory


def test_budget_meter_is_a_process_singleton() -> None:
    """AC23.4.7: get_budget_meter returns the same instance, and clients share it."""
    factory._budget_meter = None  # reset any prior state for a deterministic check
    first = factory.get_budget_meter()
    second = factory.get_budget_meter()
    assert first is second

    client_a = factory.get_llm_client()
    client_b = factory.get_llm_client()
    # Both clients hold the *same* meter, so spend accumulates across calls.
    assert client_a._cost is client_b._cost
    assert client_a._cost is first
