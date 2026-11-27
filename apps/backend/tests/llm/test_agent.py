"""The one model entry point: content parts, the fake model, the request guard and the error text (#3153)."""

import asyncio

import pytest
from infra2_sdk.llm import DecodingSpec
from pydantic_ai import BinaryContent, ImageUrl
from pydantic_ai.exceptions import ModelHTTPError

import src.llm.extension.agent as agent_module
from src.llm import ModelCallFailed, ModelFailureKind
from src.llm.extension.agent import (
    CallSite,
    complete_text,
    iterate_text,
    stream_text,
    to_message_history,
    to_user_content,
)

DECODING = DecodingSpec(decoding_version="test.v1", thinking=False, timeout=5.0)
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


async def test_the_token_cap_reaches_sdk_unchanged_and_zai_maps_it_to_extra_body(fake_llm) -> None:
    """`DecodingSpec.max_tokens` passes unchanged to `create_llm_agent`, which maps it for Z.AI."""
    from infra2_sdk.llm import LlmSettings, create_llm_agent

    sent = fake_llm("ok")
    await complete_text(
        SITE,
        "small",
        "x",
        decoding=DecodingSpec(decoding_version="test.v1", thinking=False, max_tokens=321, timeout=5.0),
        extra_body={"do_sample": False},
    )
    assert sent.extra_bodies == [{"do_sample": False}] and sent.decodings[0].max_tokens == 321

    sdk_agent = create_llm_agent(
        LlmSettings(provider="zai", api_key="test-key", base_url="https://api.z.ai/api/paas/v4"),
        role="small",
        decoding=DecodingSpec(decoding_version="test.v1", thinking=False, max_tokens=321, timeout=5.0),
    )
    assert sdk_agent.model.wrapped.settings["extra_body"]["max_tokens"] == 321


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
    with pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "SECRET-ACCOUNT-1234", decoding=DECODING, max_attempts=1)
    error = raised.value
    assert error.kind is ModelFailureKind.RATE_LIMIT and "429" in str(error)
    # Neither the message of the error nor the text of its cause holds the prompt.
    assert "SECRET-ACCOUNT-1234" not in str(error) and "SECRET-ACCOUNT-1234" not in str(error.__cause__)


def test_a_file_part_with_a_bad_payload_is_refused_not_turned_into_an_empty_document() -> None:
    import base64

    good = base64.b64encode(b"%PDF").decode()
    for bad in (
        {"type": "file", "file": {"file_data": "data:application/pdf;base64,@@@@"}},
        {"type": "file", "file": {"file_data": f"data:application/pdf;base64,{good[:4]}@{good[4:]}"}},
        {"type": "file", "file": {"file_data": "data:application/pdf;base64,"}},
        {"type": "file", "file": {"file_data": "data:application/pdf;base64"}},
        {"type": "file", "file": {"file_data": f"data:;base64,{good}"}},
        {"type": "file", "file": {"file_data": f"DATA:application/pdf;base64,{good}"}},
        {"type": "file", "file": {}},
        {"type": "file", "file": "text"},
        {"type": "file"},
        {"type": "image_url"},
        {"type": "image_url", "image_url": "https://example.com/a.png"},
    ):
        with pytest.raises(ValueError):
            to_user_content([bad])


async def test_the_body_may_not_carry_thinking_or_a_second_token_cap(fake_llm) -> None:
    fake_llm("ok")
    with pytest.raises(ValueError, match="DecodingSpec.thinking"):
        await complete_text(SITE, "small", "x", decoding=DECODING, extra_body={"thinking": {"type": "disabled"}})
    with pytest.raises(ValueError, match="DecodingSpec.max_tokens"):
        await complete_text(
            SITE,
            "small",
            "x",
            decoding=DecodingSpec(decoding_version="test.v1", thinking=False, max_tokens=20, timeout=5.0),
            extra_body={"max_tokens": 99},
        )


async def test_the_token_cap_reaches_sdk_unchanged_across_providers(fake_llm, monkeypatch) -> None:
    """Both `zai` and other providers forward `DecodingSpec.max_tokens` straight to `create_llm_agent`."""
    from src.config import settings

    sent = fake_llm("ok")
    spec = DecodingSpec(decoding_version="test.v1", thinking=False, max_tokens=77, timeout=5.0)
    await complete_text(SITE, "small", "x", decoding=spec)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "ai_api_key", "a-key")
    await complete_text(SITE, "small", "x", decoding=spec)
    assert [d.max_tokens for d in sent.decodings] == [77, 77]
    assert sent.extra_bodies == [None, None]


async def test_the_iterator_of_stream_text_refuses_use_after_the_block(fake_llm) -> None:
    fake_llm("one reply")
    async with stream_text(SITE, "small", "x", decoding=DECODING) as pieces:
        pass
    with pytest.raises(RuntimeError, match="used after its block closed"):
        [piece async for piece in pieces]


async def test_system_and_history_reach_the_model_as_instructions_and_earlier_turns(fake_llm) -> None:
    sent = fake_llm("reply")
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    assert await complete_text(SITE, "small", "q2", decoding=DECODING, system="Be brief.", history=history) == "reply"
    request = sent.requests[0]
    assert sent == ["q2"] and request[-1].instructions == "Be brief."
    assert [type(message).__name__ for message in request] == ["ModelRequest", "ModelResponse", "ModelRequest"]
    assert (request[0].parts[0].content, request[1].parts[0].content) == ("q1", "a1")
    async with stream_text(SITE, "small", "q3", decoding=DECODING, system="Be brief.", history=history) as pieces:
        assert "".join([piece async for piece in pieces]) == "reply"
    assert sent.requests[1][-1].instructions == "Be brief." and len(sent.requests[1]) == 3
    # No system and no history is the same call as before.
    await complete_text(SITE, "small", "plain", decoding=DECODING)
    assert len(sent.requests[2]) == 1 and sent.requests[2][0].instructions is None


def test_history_accepts_user_and_assistant_turns_only() -> None:
    assert to_message_history([]) == []
    with pytest.raises(ValueError, match="Unsupported history role: 'system'"):
        to_message_history([{"role": "system", "content": "a system prompt is not a turn"}])


def _open(site=SITE, **kwargs):
    return iterate_text(site, "small", "q", decoding=DECODING, max_attempts=1, **kwargs)


async def test_iterate_text_can_be_read_and_closed_in_different_tasks(fake_llm) -> None:
    """Review of #3203: the router reads the first chunk in the task of the request and the rest in another task.
    `stream_text` raised a context error and a cancel-scope error there."""
    chunks = [f"chunk{i} " for i in range(30)]
    fake_llm(chunks)
    pieces = _open()
    first = await asyncio.create_task(anext(pieces))  # task A: opens the stream

    async def rest() -> list[str]:  # task B: reads the rest
        return [piece async for piece in pieces]

    assert [first, *await asyncio.create_task(rest())] == chunks


async def test_iterate_text_closes_from_another_task_and_leaves_no_task_behind(fake_llm) -> None:
    fake_llm([f"chunk{i} " for i in range(1000)])
    before = len(asyncio.all_tasks())
    pieces = _open()
    assert await asyncio.create_task(anext(pieces)) == "chunk0 "
    await asyncio.wait_for(asyncio.create_task(pieces.aclose()), timeout=5)  # task B closes it after one chunk
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) == before


async def test_iterate_text_raises_the_failure_of_the_call_in_the_task_of_the_reader(fake_llm, monkeypatch) -> None:
    failures_counter: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_module, "record_llm_call_failure", lambda *, call_site, kind: failures_counter.append((call_site, kind))
    )
    fake_llm(["a ", "b ", ModelHTTPError(status_code=500, model_name="m", body="x")])
    seen: list[str] = []
    with pytest.raises(ModelCallFailed) as raised:
        async for piece in _open():
            seen.append(piece)
    assert (seen, raised.value.kind, failures_counter) == (
        ["a ", "b "],
        ModelFailureKind.UNAVAILABLE,
        [("reconciliation.semantic_score", "unavailable")],
    )

    fake_llm(ModelHTTPError(status_code=429, model_name="m", body="x"))  # a failure before the first chunk
    with pytest.raises(ModelCallFailed) as before:
        await anext(_open())
    assert before.value.kind is ModelFailureKind.RATE_LIMIT


async def test_iterate_text_passes_an_error_of_the_callers_argument_unchanged(fake_llm) -> None:
    fake_llm("x")
    with pytest.raises(ValueError, match="Unsupported content part"):
        await anext(iterate_text(SITE, "small", [{"type": "bogus"}], decoding=DECODING))


async def test_iterate_text_forwards_an_error_that_is_not_an_exception_instead_of_hanging_the_reader(fake_llm) -> None:
    """A `BaseException` (the test guard `UnexpectedExternalIO`, `KeyboardInterrupt`) ends the producer task: the reader
    must get it, not wait on an empty queue for ever."""
    from tests._support.guards import UnexpectedExternalIO

    fake_llm(["a ", UnexpectedExternalIO("a guard refused an I/O call")])
    seen: list[str] = []

    async def read() -> None:
        async for piece in _open():
            seen.append(piece)

    with pytest.raises(UnexpectedExternalIO, match="a guard refused"):
        await asyncio.wait_for(read(), timeout=5)
    assert seen == ["a "]
