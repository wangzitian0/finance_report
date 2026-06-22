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
from decimal import Decimal
from pathlib import Path

import pytest

from src.llm.cassette import CassetteMode, current_mode
from src.services.ai_streaming import accumulate_stream, stream_ai_json

# These drive the real LLM transport, so they run only in record mode (freeze the
# real response) or replay mode (serve the committed cassette — no key/network).
# In the normal off-mode shards there is no key, so they SKIP; run them with
# LLM_CASSETTE_MODE=record (to (re)record) or =replay (to assert against cassettes).
pytestmark = pytest.mark.skipif(
    current_mode() is CassetteMode.OFF,
    reason="cassette record/replay only (set LLM_CASSETTE_MODE=record to record, replay to run)",
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
# Ground truth the test asserts on replay (opening + net == closing). Decimal,
# never float — money invariants must not accrue float rounding artefacts.
_TEXT_OPENING = Decimal("100.00")
_TEXT_CLOSING = Decimal("130.00")
_TEXT_TOLERANCE = Decimal("0.01")
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

    # Decimal end-to-end (str() before Decimal so a JSON float never seeds it).
    opening = Decimal(str(data["opening_balance"]))
    closing = Decimal(str(data["closing_balance"]))
    txns = data["transactions"]
    net = sum((Decimal(str(t["amount"])) for t in txns), Decimal("0"))

    assert abs(opening - _TEXT_OPENING) <= _TEXT_TOLERANCE
    assert abs(closing - _TEXT_CLOSING) <= _TEXT_TOLERANCE
    assert len(txns) == _TEXT_TXN_COUNT
    # Balance-chain invariant on the LLM's extraction (the #1254-class oracle).
    assert abs((opening + net) - closing) <= _TEXT_TOLERANCE


_VISION_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "vision" / "simple_statement.pdf"


async def test_AC23_6_extraction_vision_happy_path_via_replay() -> None:
    """Text+image (vision) extraction happy-path through the default-config vision
    path (OCR_MODEL == VISION_MODEL == glm-4.6v), in replay.

    Drives a committed FIXED-BYTES statement PDF through ``ExtractionService``: the
    app renders it to a PNG (deterministic), the vision OCR call replays the frozen
    glm-4.6v response, and the result must pass the app's own balance validation —
    which uses amount+direction (IN/OUT), exactly how glm-4.6v reads a statement.
    NO network, NO key in replay.
    """
    from src.services.extraction.service import ExtractionService
    from src.services.validation import validate_balance

    service = ExtractionService()
    service.api_key = "replay"  # passes the key-check; replay performs no live call
    result = await service.extract_financial_data(
        file_content=_VISION_PDF.read_bytes(),
        institution="ACME",
        file_type="pdf",
        filename="simple_statement.pdf",
    )
    assert len(result["transactions"]) == 3
    # The app's own balance oracle (amount+direction aware) must reconcile.
    assert validate_balance(result)["balance_valid"] is True


_DUP_MODEL = "glm-5.2"
_DUP_MAX_TOKENS = 512
_DUP_STATEMENT = (
    "Opening balance: 1000.00\n"
    "2026-02-01  Deposit ABC        +250.00\n"
    "2026-02-01  Deposit ABC        +250.00\n"  # genuine same-date same-amount duplicate
    "2026-02-03  Service fee         -10.00\n"
    "Closing balance: 1490.00\n"
)
_DUP_MESSAGES = [{"role": "user", "content": _TEXT_PROMPT + "\n\n" + _DUP_STATEMENT}]
_DUP_OPENING = Decimal("1000.00")
_DUP_CLOSING = Decimal("1490.00")
_DUP_DEPOSIT = Decimal("250.00")


async def test_AC23_6_extraction_1254_class_dedup_balance_via_replay() -> None:
    """#1254-class duplicate-deposit behaviour through the LLM path in replay.

    Two genuine same-date/same-amount deposits must BOTH survive extraction (the
    #1254 bug dropped one), and the balance chain must reconcile — asserted on the
    frozen LLM output with NO network and NO key.
    """
    stream = stream_ai_json(
        messages=_DUP_MESSAGES,
        model=_DUP_MODEL,
        max_tokens=_DUP_MAX_TOKENS,
        temperature=0.0,
        thinking={"type": "disabled"},
    )
    content = await accumulate_stream(stream)
    data = _loads_tolerant(content)

    opening = Decimal(str(data["opening_balance"]))
    closing = Decimal(str(data["closing_balance"]))
    txns = data["transactions"]
    amounts = [Decimal(str(t["amount"])) for t in txns]
    net = sum(amounts, Decimal("0"))

    # Both same-amount deposits survived (the #1254 oracle: count is preserved)
    # and no row was dropped or invented overall.
    assert len(txns) == 3
    assert sum(1 for a in amounts if a == _DUP_DEPOSIT) == 2
    assert abs(opening - _DUP_OPENING) <= _TEXT_TOLERANCE
    assert abs(closing - _DUP_CLOSING) <= _TEXT_TOLERANCE
    assert abs((opening + net) - closing) <= _TEXT_TOLERANCE
