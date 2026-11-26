"""Replay of a recorded model reply for the reconciliation score (#3153).

Record again with: `LLM_API_KEY=<key> pytest --record-mode=rewrite tests/llm/test_semantic_scoring_replay.py`.
"""

from pathlib import Path

import pytest

from infra2_sdk.llm import DecodingSpec
from src.llm.extension.agent import CallSite, complete_text
from src.llm.extension.semantic_scoring import ai_semantic_score
from src.reconciliation.base.prompts import build_reconciliation_prompt

SAME_PAYMENT = build_reconciliation_prompt("GIRO SALARY ACME PTE LTD", "Monthly salary from Acme", 0, 100.0)
CASSETTE = (
    Path(__file__).parent
    / "cassettes"
    / "test_semantic_scoring_replay"
    / "test_the_recorded_reply_gives_a_high_score.yaml"
)


@pytest.mark.vcr
async def test_the_recorded_reply_gives_a_high_score(vcr_llm) -> None:
    """The prompt that production builds, sent through the SDK agent, answered by the recorded reply."""
    assert await ai_semantic_score(SAME_PAYMENT) >= 80


@pytest.mark.vcr(str(CASSETTE), record_mode="none")
async def test_a_changed_prompt_has_no_recorded_reply(vcr_llm) -> None:
    """A recording answers only the request that it was recorded for, so a prompt change fails the replay."""
    changed = SAME_PAYMENT.replace("Monthly salary from Acme", "Office rent")
    with pytest.raises(Exception) as raised:
        await complete_text(
            CallSite.RECONCILIATION_SEMANTIC_SCORE,
            "small",
            changed,
            decoding=DecodingSpec(decoding_version="reconciliation.semantic_score.v1", thinking=False, timeout=30.0),
            max_attempts=1,
        )
    assert (
        "CannotOverwriteExistingCassetteException" in type(raised.value).__name__
        or "cassette" in str(raised.value).lower()
    )
