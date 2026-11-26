"""Replay of recorded calls through the entry point: the request that the SDK really sends (#3153).

Record again with: `LLM_API_KEY=<key> pytest --record-mode=rewrite tests/llm/test_agent_replay.py`.
"""

import pytest

from infra2_sdk.llm import DecodingSpec
from src.llm.extension.agent import CallSite, complete_text

PROMPT = "Write a 400-word essay about the sea."


@pytest.mark.vcr
async def test_a_token_cap_of_20_stops_the_reply_of_the_provider(vcr_llm) -> None:
    """Recorded: `max_tokens` 20 in the request body gave a reply of 20 tokens. With `max_completion_tokens` the
    provider wrote 504 tokens. The replay matches the request body, so it fails if the cap leaves `max_tokens`."""
    reply = await complete_text(
        CallSite.RECONCILIATION_SEMANTIC_SCORE,
        "small",
        PROMPT,
        decoding=DecodingSpec(decoding_version="test.v1", thinking=False, max_tokens=20, timeout=60.0),
        max_attempts=1,
    )
    assert 0 < len(reply) < 200
