"""The one model entry point: content parts, the fake model, the request guard and the error text (#3153)."""

import pytest
from pydantic_ai import ImageUrl
from pydantic_ai.exceptions import ModelHTTPError

from infra2_sdk.runtime import DecodingSpec
from pydantic_ai import BinaryContent

from src.llm.extension.agent import CallSite, complete_text, stream_text, to_user_content

DECODING = DecodingSpec("test.v1", thinking=False, timeout=5.0)
SITE = CallSite.RECONCILIATION_SEMANTIC_SCORE


def test_to_user_content_maps_the_media_dicts_to_parts() -> None:
    parts = to_user_content(
        [
            {"type": "text", "text": "read the page"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            "plain",
        ]
    )
    assert parts[0] == "read the page" and parts[2] == "plain"
    assert isinstance(parts[1], ImageUrl) and parts[1].url == "data:image/png;base64,AAAA"
    assert to_user_content("one string") == "one string"
    with pytest.raises(ValueError, match="Unsupported content part: 'audio'"):
        to_user_content([{"type": "audio"}])


async def test_complete_text_and_stream_text_return_the_reply_of_the_model(fake_llm) -> None:
    sent = fake_llm(lambda content: f"echo:{content}")
    assert await complete_text(SITE, "small", "hello", decoding=DECODING) == "echo:hello"
    async with stream_text(SITE, "small", "again", decoding=DECODING) as pieces:
        text = "".join([piece async for piece in pieces])
    assert text == "echo:again" and sent == ["hello", "again"]


async def test_stream_text_closes_at_once_when_the_loop_stops_early_or_raises(fake_llm) -> None:
    """A plain async generator closed by the garbage collector cancels the consumer task (review of #3194)."""
    fake_llm("a reply that is long enough to stop in the middle")
    async with stream_text(SITE, "small", "x", decoding=DECODING) as pieces:
        async for _piece in pieces:
            break
    with pytest.raises(KeyError):
        async with stream_text(SITE, "small", "x", decoding=DECODING) as pieces:
            async for _piece in pieces:
                raise KeyError("the consumer failed")
    # The task of the test was not cancelled: this await completes.
    assert (
        await complete_text(SITE, "small", "y", decoding=DECODING)
        == "a reply that is long enough to stop in the middle"
    )


async def test_the_token_cap_is_sent_as_max_tokens_in_the_extra_body(fake_llm) -> None:
    """Z.AI ignores `max_completion_tokens`, which is what the SDK sends for `DecodingSpec.max_tokens`."""
    sent = fake_llm("ok")
    await complete_text(
        SITE,
        "small",
        "x",
        decoding=DecodingSpec("test.v1", thinking=False, max_tokens=321, timeout=5.0),
        extra_body={"do_sample": False},
    )
    assert sent.extra_bodies == [{"do_sample": False, "max_tokens": 321}] and sent.decodings[0].max_tokens is None


def test_to_user_content_maps_a_file_part_to_binary_content() -> None:
    import base64

    data = base64.b64encode(b"%PDF-1.4 test").decode()
    (part,) = to_user_content(
        [{"type": "file", "file": {"filename": "s.pdf", "file_data": f"data:application/pdf;base64,{data}"}}]
    )
    assert isinstance(part, BinaryContent) and part.data == b"%PDF-1.4 test" and part.media_type == "application/pdf"
    with pytest.raises(ValueError, match="base64 data URI"):
        to_user_content([{"type": "file", "file": {"file_data": "https://example.com/s.pdf"}}])


async def test_a_model_request_without_a_fake_or_a_recording_is_refused(monkeypatch) -> None:
    """With a key present, the session guard of pydantic-ai stops the request before a socket opens."""
    from src.config import settings

    monkeypatch.setattr(settings, "ai_api_key", "a-key-that-must-never-leave-the-test")
    with pytest.raises(Exception) as raised:
        await complete_text(SITE, "small", "hello", decoding=DECODING, max_attempts=1)
    assert "ALLOW_MODEL_REQUESTS" in str(raised.value) or "not allowed" in str(raised.value)


async def test_a_model_error_does_not_carry_the_prompt_or_the_provider_body(fake_llm) -> None:
    """#3058: the error text that a caller logs holds the class, the status and the provider code only."""

    def fail(content):
        raise ModelHTTPError(
            status_code=429, model_name="m", body={"error": {"code": "1302", "message": f"echo {content}"}}
        )

    fake_llm(fail)
    with pytest.raises(ModelHTTPError) as raised:
        await complete_text(SITE, "small", "SECRET-ACCOUNT-1234", decoding=DECODING, max_attempts=1)
    assert "SECRET-ACCOUNT-1234" not in str(raised.value) and "429" in str(raised.value)
