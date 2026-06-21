"""Extraction tests routed through the streaming-cassette bridge in replay.

EPIC-023 AC23.6 / issue #1306. These wire the first batch of LLM-touching
extraction tests onto the cassette replay path so the parse pipeline's LLM path
is exercised in CI WITHOUT a key or network. The frozen responses are REAL GLM
(glm-5.2 / glm-4.6v) completions recorded via the GLM coding plan; in replay
they are served from committed cassettes (zero key, zero network).

Recording (operator-only, needs the provider key):

    AI_PROVIDER=zai AI_BASE_URL=https://api.z.ai/api/coding/paas/v4 \\
    AI_API_KEY=$GLM_CODING_TOKEN PRIMARY_MODEL=glm-5.2 \\
    LLM_CASSETTE_MODE=record \\
        uv run pytest tests/extraction/test_extraction_cassette_replay.py

Tests with no cassette yet stay `pytest.skip`-marked (per-test, not module-wide)
so PR CI stays green and the not-yet-recorded path is unmistakably flagged.

Boundary: these assert provider-agnostic response *handling* + the balance/dedup
invariants through the parse pipeline. Provider-specific correctness on unseen
documents remains the staging ``-m llm`` live gate's job (untouched here).
"""

from __future__ import annotations

import json

import pytest

from src.llm.cassette import CassetteMode, current_mode
from src.services.ai_streaming import accumulate_stream, stream_ai_json

# These drive the real LLM transport, so they are meaningful only in replay (the
# committed cassette serves the frozen response with no key/network). In the
# normal off-mode shards there is no key, so self-gate to replay: they SKIP in
# shards and RUN in the dedicated cassette-replay CI step (LLM_CASSETTE_MODE=replay).
pytestmark = pytest.mark.skipif(
    current_mode() is not CassetteMode.REPLAY,
    reason="cassette-replay only (run with LLM_CASSETTE_MODE=replay)",
)

# --- Deterministic, anonymised inputs (synthetic; no real financial data). ---
# The fingerprint keys on (role + messages + decode params), so these MUST stay
# byte-identical to what was recorded for replay to hit.
_TEXT_MODEL = "glm-5.2"
_TEXT_MAX_TOKENS = 512
_TEXT_PROMPT = (
    "Extract this bank statement as strict JSON only (no prose, no markdown "
    "fence) with keys opening_balance, closing_balance, transactions (a list of "
    "{date, description, amount}). Amounts are negative for debits, positive for "
    "credits."
)
_TEXT_STATEMENT = (
    "Opening balance: 100.00\n"
    "2026-01-02  Coffee shop        -5.00\n"
    "2026-01-05  Salary credit      +50.00\n"
    "2026-01-09  Groceries          -15.00\n"
    "Closing balance: 130.00\n"
)
_TEXT_MESSAGES = [{"role": "user", "content": _TEXT_PROMPT + "\n\n" + _TEXT_STATEMENT}]
# Ground truth the cassette is validated against (opening + net == closing).
_TEXT_OPENING = 100.00
_TEXT_CLOSING = 130.00
_TEXT_TXN_COUNT = 3


def _loads_tolerant(content: str) -> dict:
    """Parse a JSON object, stripping a ```json fence if the model added one."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


async def test_AC23_6_extraction_text_happy_path_via_replay() -> None:
    """Text extraction happy-path through ``litellm_stream`` replay.

    Drives a known anonymised text statement through the JSON-extraction transport
    and asserts the LLM-read numbers satisfy the balance chain
    (opening + Σamounts == closing) and the expected transaction count — exercised
    with NO network and NO API key in replay. A frozen-wrong response (LLM misread
    a number) fails these assertions, which is the point.
    """
    stream = stream_ai_json(
        messages=_TEXT_MESSAGES,
        model=_TEXT_MODEL,
        max_tokens=_TEXT_MAX_TOKENS,
        temperature=0.0,
        thinking={"type": "disabled"},
    )
    content = await accumulate_stream(stream)
    data = _loads_tolerant(content)

    opening = float(data["opening_balance"])
    closing = float(data["closing_balance"])
    txns = data["transactions"]
    net = sum(float(t["amount"]) for t in txns)

    assert opening == pytest.approx(_TEXT_OPENING, abs=0.01)
    assert closing == pytest.approx(_TEXT_CLOSING, abs=0.01)
    assert len(txns) == _TEXT_TXN_COUNT
    # Balance-chain invariant on the LLM's extraction (the #1254-class oracle).
    assert (opening + net) == pytest.approx(closing, abs=0.01)


@pytest.mark.skip(reason="needs real vision cassette: record glm-4.6v (see module docstring / issue #1306)")
async def test_AC23_6_extraction_vision_happy_path_via_replay() -> None:
    """Text+image (vision) extraction happy-path through the default-config vision
    path (OCR_MODEL==VISION_MODEL). Pending a recorded glm-4.6v cassette."""
    pytest.skip("vision cassette not yet recorded")


@pytest.mark.skip(reason="needs real #1254-class cassette (see module docstring / issue #1306)")
async def test_AC23_6_extraction_1254_class_dedup_balance_via_replay() -> None:
    """#1254-class dedup/balance behaviour through the LLM path in replay. Pending
    a recorded cassette of the duplicate-deposit edge case."""
    pytest.skip("#1254-class cassette not yet recorded")
