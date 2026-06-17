"""Factory wiring: the budget meter must be a shared singleton (EPIC-023 PR5).

A fresh ``DailyBudgetMeter`` per call would reset ``spent_today`` to zero, so the
daily limit would never be enforced. ``get_budget_meter`` must hand back one
shared instance (the live transport in ``ai_streaming`` records spend onto it).
"""

from __future__ import annotations

import src.llm.factory as factory


def test_budget_meter_is_a_process_singleton() -> None:
    """AC23.4.7: get_budget_meter returns the same shared meter across calls."""
    factory._budget_meter = None  # reset any prior state for a deterministic check
    first = factory.get_budget_meter()
    second = factory.get_budget_meter()
    assert first is second
