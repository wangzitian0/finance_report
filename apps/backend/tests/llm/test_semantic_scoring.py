"""The semantic score of the reconciliation, through the one model entry point (#3153)."""

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from src.llm.extension.semantic_scoring import ai_semantic_score


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"similarity_score": 92, "reasoning": "Both refer to salary"}', 92),
        ('{"similarity_score": 15, "reasoning": "Completely different"}', 15),
        ('{"similarity_score": 150, "reasoning": "Over 100"}', 100),
        ('{"similarity_score": -4}', 0),
        ("  ", 50),
        ("not json", 50),
        ('{"reasoning": "no score"}', 50),
    ],
)
async def test_ai_semantic_score_reads_and_clamps_the_reply(fake_llm, reply: str, expected: int) -> None:
    sent = fake_llm(reply)
    assert await ai_semantic_score("compare A with B") == expected
    assert sent == ["compare A with B"]


async def test_ai_semantic_score_falls_back_when_the_model_call_fails(fake_llm) -> None:
    def fail(_content):
        raise ModelHTTPError(status_code=502, model_name="test", body={"error": "upstream"})

    fake_llm(fail)
    assert await ai_semantic_score("compare A with B") == 50


async def test_ai_semantic_score_falls_back_when_no_model_is_reachable() -> None:
    """No fake model and no recording: the test session forbids a model request, and the score is neutral."""
    assert await ai_semantic_score("compare A with B") == 50
