"""Factory wiring: the usage meter must be a shared singleton (EPIC-023).

A fresh meter per call would reset the running request/token totals, so
``get_usage_meter`` must hand back one shared instance (the live transport in
``ai_streaming`` records onto it).
"""

from __future__ import annotations

import src.llm.factory as factory


def test_usage_meter_is_a_process_singleton() -> None:
    """AC23.4.7: get_usage_meter returns the same shared meter across calls."""
    factory._usage_meter = None  # reset any prior state for a deterministic check
    first = factory.get_usage_meter()
    second = factory.get_usage_meter()
    assert first is second
