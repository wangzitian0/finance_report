"""Extraction tests routed through the streaming-cassette bridge in replay.

SCAFFOLD ONLY (EPIC-023 AC23.6 / issue #1306). These wire the first batch of
LLM-touching extraction tests onto the cassette replay path so the parse
pipeline's LLM path is exercised in CI WITHOUT a key or network. They are
**skipped in this PR's CI** because the real cassettes do not exist yet — the
streaming bridge half (this PR) deliberately does NOT record real extraction
cassettes (no GLM token). The human operator records them afterwards:

    LLM_CASSETTE_MODE=record make llm-record \\
        ARGS='tests/extraction/test_extraction_cassette_replay.py -m needs_real_cassette'

then removes the ``needs_real_cassette`` skip (flip the marker) so they run in
the dedicated replay CI step. The frozen responses must be ground-truth
validated (``correctness`` tag) at record time; the synthetic placeholders here
are NOT a substitute and are intentionally absent.

Until then, every test below is collected but SKIPPED — PR CI stays green and
the not-yet-recorded path is unmistakably flagged, never silently faked.

Boundary: these assert provider-agnostic response *handling* through the parse
pipeline; provider-specific correctness on unseen documents remains the staging
``-m llm`` live gate's job (which this PR leaves untouched).
"""

from __future__ import annotations

import pytest

# Module-level skip: the cassettes for these scenes have not been recorded yet.
# Recording instructions are in the module docstring and the PR final report.
pytestmark = [
    pytest.mark.needs_real_cassette,
    pytest.mark.skip(reason="needs real cassette: run make llm-record (see module docstring / issue #1306)"),
]

_RECORD_HINT = (
    "Record with: LLM_CASSETTE_MODE=record make llm-record "
    "ARGS='tests/extraction/test_extraction_cassette_replay.py -m needs_real_cassette', "
    "then remove the needs_real_cassette skip."
)


async def test_AC23_6_extraction_text_happy_path_via_replay() -> None:
    """Text extraction happy-path through ``litellm_stream`` replay.

    When the real cassette exists: drive a known anonymised text statement through
    ``ExtractionService`` with ``LLM_CASSETTE_MODE=replay`` and assert the parsed
    transactions + closing balance match the ground-truth the cassette was
    validated against — exercised with NO network and NO API key.
    """
    pytest.skip(_RECORD_HINT)


async def test_AC23_6_extraction_vision_happy_path_via_replay() -> None:
    """Text+image (vision) extraction happy-path through ``litellm_stream`` replay.

    When the real cassette exists: feed a committed FIXED-BYTES statement image
    (never regenerated in-test, so a re-render cannot spuriously invalidate the
    cassette) through the default-config vision path (OCR_MODEL==VISION_MODEL) and
    assert the parsed result matches ground-truth — no network, no key.
    """
    pytest.skip(_RECORD_HINT)


async def test_AC23_6_extraction_1254_class_dedup_balance_via_replay() -> None:
    """#1254-class dedup/balance behaviour through the LLM path in replay.

    When the real cassette exists: replay a statement whose LLM output previously
    triggered the #1254 duplicate/balance edge case and assert the dedup + balance
    invariants hold end-to-end through the cassette-backed parse — no network, no
    key.
    """
    pytest.skip(_RECORD_HINT)
