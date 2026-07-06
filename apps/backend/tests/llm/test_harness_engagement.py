"""AC-llm.10.7 (CF-1 lock): the test harness must engage the cassette layer.

The whole transparency contract rests on conftest engaging the layer exactly
once. If that bootstrap is ever dropped, every LLM-touching test would fall to
live passthrough (red, but with a confusing "provider not configured" message).
This lock fails FIRST with the precise diagnosis.
"""

from __future__ import annotations

from src.llm.extension.cassette import layer_engaged


def test_AC_llm_10_7_harness_engages_the_cassette_layer():
    """AC-llm.10.7: under pytest the layer is engaged (conftest bootstrap)."""
    assert layer_engaged(), (
        "the cassette layer is NOT engaged — tests/conftest.py's pytest_configure "
        "must set LLM_CASSETTE_ENGAGE=1 (the harness is the single sanctioned "
        "bootstrap point; without it every LLM test silently goes live)"
    )
