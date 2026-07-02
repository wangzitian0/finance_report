"""Classify proposer vs the REAL GLM response shape (EPIC-018 AC18.15.3, #1560).

Two layers:
1. ``test_record_or_replay_real_provider`` — cassette record/replay through the
   real transport (skips when ``LLM_CASSETTE_MODE`` is off, like the extraction
   replay tests). Recording (operator-only, needs the provider key):

       AI_PROVIDER=zai AI_BASE_URL=https://api.z.ai/api/coding/paas/v4 \
       AI_API_KEY=$GLM_CODING_TOKEN PRIMARY_MODEL=glm-5.2 \
       LLM_CASSETTE_MODE=record uv run pytest tests/services/test_classification_cassette.py

2. ``test_frozen_real_response_parses_in_plain_ci`` — runs in NORMAL CI shards
   (no cassette mode, no network): loads the committed cassette JSON and pushes
   the frozen REAL provider response through the proposer's parse path. This is
   the gate that would have caught the staging fenced-JSON failure in CI.
"""

from __future__ import annotations

import json

import pytest

from src.llm.cassette import CASSETTE_DIR, CassetteMode, current_mode
from src.services.transaction_classification import (
    POLICY_VERSIONS,
    TransactionCategory,
    _recover_json_array,
    propose_categories,
)
from tests.factories import AtomicTransactionFactory

# Deterministic inputs: the cassette fingerprint keys on the exact messages, so
# these MUST stay byte-stable (synthetic; no real financial data).
_FIXED_TXNS = [
    ("Monthly salary deposit ACME PTE LTD", "IN"),
    ("NTUC FairPrice groceries", "OUT"),
]
_POLICY = POLICY_VERSIONS[0]
_PROMPT_MARKER = "Classify each personal-finance transaction"


def _fixed_transactions():
    from src.models.layer2 import TransactionDirection

    txns = []
    for desc, direction in _FIXED_TXNS:
        txn = AtomicTransactionFactory.build(user_id=None, description=desc)
        txn.direction = TransactionDirection.IN if direction == "IN" else TransactionDirection.OUT
        txns.append(txn)
    return txns


@pytest.mark.skipif(
    current_mode() is CassetteMode.OFF,
    reason="cassette record/replay only (LLM_CASSETTE_MODE=record to record, replay to run)",
)
@pytest.mark.asyncio
async def test_record_or_replay_real_provider():
    """AC18.15.3: the proposer handles the real provider's response shape."""
    proposals = await propose_categories(_fixed_transactions(), _POLICY)
    assert len(proposals) == 2
    assert any(p is not None for p in proposals), "real provider response must parse"
    for p in proposals:
        if p is not None:
            assert p.category in {c.value for c in _POLICY.catalog}
            assert 0 <= p.confidence <= 100


def _find_classify_cassette() -> dict | None:
    for path in CASSETTE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _PROMPT_MARKER in json.dumps(data.get("request", {})):
            return data
    return None


def test_frozen_real_response_parses_in_plain_ci():
    """AC18.15.3: the COMMITTED real GLM response parses through the proposer's
    parse path in a normal CI shard (no cassette mode, zero network) — the exact
    gate the staging fenced-JSON failure needed. If the cassette is ever
    re-recorded into a shape the parser can't handle, this fails in CI."""
    cassette = _find_classify_cassette()
    assert cassette is not None, (
        "classify cassette missing — record it: AI_PROVIDER=zai "
        "AI_BASE_URL=https://api.z.ai/api/coding/paas/v4 AI_API_KEY=$GLM_CODING_TOKEN "
        "PRIMARY_MODEL=glm-5.2 LLM_CASSETTE_MODE=record "
        "uv run pytest tests/services/test_classification_cassette.py"
    )
    content = str(cassette.get("response", {}).get("stream_text") or "")
    assert content.strip(), "cassette has an empty frozen response"

    # the proposer's exact parse path: strict json first, then array recovery
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _recover_json_array(content)
    assert isinstance(parsed, list) and parsed, (
        f"frozen REAL provider response did not parse (len={len(content)}, fenced={content.lstrip().startswith('`')})"
    )
    catalog = {c.value for c in TransactionCategory}
    valid = [item for item in parsed if isinstance(item, dict) and str(item.get("category", "")) in catalog]
    assert valid, "no catalog-valid proposal in the frozen response"
