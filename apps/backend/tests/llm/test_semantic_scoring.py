"""The semantic score of the reconciliation, through the one model entry point (#3153).

A failure is an error and never a score: 50 always means that the model said 50.
"""

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from src.llm import ModelCallFailed, ModelFailureKind
from src.llm.extension.semantic_scoring import ai_semantic_score


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"similarity_score": 92, "reasoning": "Both refer to salary"}', 92),
        ('{"similarity_score": 15, "reasoning": "Completely different"}', 15),
        ('{"similarity_score": 150, "reasoning": "Over 100"}', 100),
        ('{"similarity_score": -4}', 0),
        ('{"similarity_score": 50}', 50),
        ('{"similarity_score": "70"}', 70),
    ],
)
async def test_ai_semantic_score_reads_and_clamps_the_reply(fake_llm, reply: str, expected: int) -> None:
    sent = fake_llm(reply)
    assert await ai_semantic_score("compare A with B") == expected
    assert sent == ["compare A with B"]


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        '{"reasoning": "no score"}',
        "[1, 2]",
        '"hi"',
        "null",
        '{"similarity_score": null}',
        '{"similarity_score": "high"}',
        '{"similarity_score": 1e999}',
        '{"similarity_score": NaN}',
    ],
)
async def test_a_reply_without_a_score_is_a_bad_reply_and_not_a_neutral_score(fake_llm, reply: str) -> None:
    fake_llm(reply)
    with pytest.raises(ModelCallFailed) as raised:
        await ai_semantic_score("compare A with B")
    assert raised.value.kind is ModelFailureKind.BAD_REPLY and raised.value.call_site == "reconciliation.semantic_score"
    # The text that a caller logs holds the size of the reply, not the reply.
    assert f"{len(reply)} characters" in raised.value.summary and reply not in raised.value.summary


async def test_a_failed_model_call_is_an_error_and_not_a_score(fake_llm) -> None:
    def fail(_content):
        raise ModelHTTPError(status_code=502, model_name="test", body={"error": "upstream"})

    fake_llm(fail)
    with pytest.raises(ModelCallFailed) as raised:
        await ai_semantic_score("compare A with B")
    assert raised.value.kind is ModelFailureKind.UNAVAILABLE


async def test_a_deployment_without_a_model_is_not_configured_and_not_a_score(monkeypatch) -> None:
    """No fake model and no key: the entry point says `not_configured`; nothing gives the caller a neutral value."""
    from src.config import settings

    monkeypatch.setattr(settings, "ai_api_key", "")
    with pytest.raises(ModelCallFailed) as raised:
        await ai_semantic_score("compare A with B")
    assert raised.value.kind is ModelFailureKind.NOT_CONFIGURED
