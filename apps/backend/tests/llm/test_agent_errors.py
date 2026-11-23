"""The error contract of the entry point: each failure leaves as one `ModelCallFailed` and is counted once (#3153).

The real SDK model runs here. Only the transport (`httpx2.AsyncClient.send`) is replaced, so the kinds are those of
what the SDK really does with a provider answer, not of a fake.
"""

import asyncio
import json

import httpx2
import pytest
from infra2_sdk.runtime import DecodingSpec, allow_vcr_model_requests
from pydantic_ai.usage import UsageLimits

import src.llm.extension.agent as agent_module
from src.config import settings
from src.llm import ModelCallFailed, ModelFailureKind
from src.llm.extension.agent import CallSite, complete_text, stream_text

SITE = CallSite.RECONCILIATION_SEMANTIC_SCORE
DECODING = DecodingSpec("test.v1", thinking=False, timeout=5.0)
CHUNK = {"id": "x", "object": "chat.completion.chunk", "created": 1, "model": "glm-5.3-flash"}


def _sse(*payloads: dict, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps({**CHUNK, **payload})}\n\n" for payload in payloads]
    return ("".join(lines) + ("data: [DONE]\n\n" if done else "")).encode()


GOOD = _sse(
    {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "hello"}, "finish_reason": None}]},
    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
)


@pytest.fixture
def failures(monkeypatch):
    """Record each call of the failure counter."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_module, "record_llm_call_failure", lambda *, call_site, kind: seen.append((call_site, kind))
    )
    return seen


@pytest.fixture
def provider(monkeypatch):
    """Install a provider answer: `provider(lambda request: httpx2.Response(...))`, or a function that raises."""
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    requests: list[httpx2.Request] = []

    def install(responder):
        async def send(self, request, *args, **kwargs):
            requests.append(request)
            return responder(request)

        monkeypatch.setattr(httpx2.AsyncClient, "send", send)
        return requests

    with allow_vcr_model_requests():
        yield install


def _response(status: int, content: bytes = b"", content_type: str = "application/json"):
    return lambda request: httpx2.Response(
        status, content=content, headers={"content-type": content_type}, request=request
    )


def _raise(error_class, message: str = "failure"):
    def responder(request):
        raise error_class(message, request=request)

    return responder


PROVIDER_ANSWERS = [
    ("html page with status 200", _response(200, b"<html>maintenance</html>", "text/html"), ModelFailureKind.BAD_REPLY),
    ("empty body with status 200", _response(200, b"", "text/event-stream"), ModelFailureKind.BAD_REPLY),
    ("json error with status 200", _response(200, b'{"error": {"code": "1305"}}'), ModelFailureKind.BAD_REPLY),
    ("429", _response(429, b'{"error": {"code": "1302"}}'), ModelFailureKind.RATE_LIMIT),
    ("500", _response(500, b"upstream"), ModelFailureKind.UNAVAILABLE),
    ("503", _response(503, b"busy"), ModelFailureKind.UNAVAILABLE),
    ("401", _response(401, b'{"error": "key"}'), ModelFailureKind.REJECTED),
    ("400", _response(400, b'{"error": {"code": "1210"}}'), ModelFailureKind.REJECTED),
    ("connection refused", _raise(httpx2.ConnectError, "refused"), ModelFailureKind.UNAVAILABLE),
    ("read timeout", _raise(httpx2.ReadTimeout, "slow"), ModelFailureKind.TIMEOUT),
]


@pytest.mark.parametrize(("name", "responder", "kind"), PROVIDER_ANSWERS, ids=[case[0] for case in PROVIDER_ANSWERS])
async def test_each_provider_answer_leaves_as_one_error_with_its_kind(
    name, responder, kind, provider, failures
) -> None:
    provider(responder)
    with pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "the prompt text", decoding=DECODING, max_attempts=1)
    error = raised.value
    assert (error.kind, error.call_site, failures) == (kind, SITE.value, [(SITE.value, kind.value)])
    # The text that a caller can log holds no prompt text.
    assert "the prompt text" not in str(error) and isinstance(error.__cause__, Exception)


async def test_a_good_answer_gives_the_text_and_counts_nothing(provider, failures) -> None:
    requests = provider(_response(200, GOOD, "text/event-stream"))
    assert await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1) == "hello"
    assert len(requests) == 1 and failures == []


async def test_a_transient_failure_is_retried_by_the_sdk_and_counted_only_when_it_stays(provider, failures) -> None:
    answers = iter([_response(500, b"upstream"), _response(200, GOOD, "text/event-stream")])
    requests = provider(lambda request: next(answers)(request))
    assert await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=2) == "hello"
    assert len(requests) == 2 and failures == []


async def test_a_missing_key_is_not_configured(monkeypatch, failures) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "")
    with allow_vcr_model_requests(), pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING)
    assert raised.value.kind is ModelFailureKind.NOT_CONFIGURED and failures == [(SITE.value, "not_configured")]


async def test_an_unsupported_provider_is_not_configured(monkeypatch, failures) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_provider", "no-such-provider")
    with allow_vcr_model_requests(), pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING)
    assert raised.value.kind is ModelFailureKind.NOT_CONFIGURED


async def test_a_usage_limit_is_its_own_kind(provider, failures) -> None:
    provider(_response(200, GOOD, "text/event-stream"))
    with pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING, usage_limits=UsageLimits(request_limit=0))
    assert raised.value.kind is ModelFailureKind.USAGE_LIMIT


async def test_an_error_that_the_sdk_cannot_class_is_unclassified_and_logged_as_an_error(
    fake_llm, failures, monkeypatch
) -> None:
    """An `AssertionError` below the SDK becomes a bare `RuntimeError`: nothing says what it was, so it is an ERROR."""
    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_module,
        "logger",
        type(
            "L",
            (),
            {
                "error": staticmethod(lambda event, **fields: logged.append(("error", fields["kind"]))),
                "warning": staticmethod(lambda event, **fields: logged.append(("warning", fields["kind"]))),
            },
        ),
    )

    def broken(_content):
        raise AssertionError("a bug")

    fake_llm(broken)
    with pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1)
    assert raised.value.kind is ModelFailureKind.UNCLASSIFIED
    assert failures == [(SITE.value, "unclassified")] and logged == [("error", "unclassified")]


async def test_an_expected_kind_is_logged_as_a_warning(provider, failures, monkeypatch) -> None:
    logged: list[str] = []
    monkeypatch.setattr(
        agent_module,
        "logger",
        type(
            "L",
            (),
            {
                "error": staticmethod(lambda event, **fields: logged.append("error")),
                "warning": staticmethod(lambda event, **fields: logged.append("warning")),
            },
        ),
    )
    provider(_response(429, b"{}"))
    with pytest.raises(ModelCallFailed):
        await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1)
    assert logged == ["warning"]


async def test_the_local_refusal_of_a_test_run_is_not_wrapped(monkeypatch, failures) -> None:
    """With the session guard on and a key, the model request is refused. That is a test error, not a model failure."""
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    with pytest.raises(RuntimeError, match="not allowed") as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1)
    assert not isinstance(raised.value, ModelCallFailed) and failures == []


async def test_the_arguments_of_the_caller_and_a_cancellation_are_not_wrapped(fake_llm, failures) -> None:
    fake_llm("x")
    with pytest.raises(ValueError, match="DecodingSpec.thinking"):
        await complete_text(SITE, "small", "x", decoding=DECODING, extra_body={"thinking": {}})

    def cancelled(_content):
        raise asyncio.CancelledError

    fake_llm(cancelled)
    with pytest.raises(asyncio.CancelledError):
        await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1)
    assert failures == []


async def test_stream_text_wraps_a_failure_of_the_call_and_not_an_error_of_the_consumer(provider, failures) -> None:
    provider(_response(500, b"upstream"))
    with pytest.raises(ModelCallFailed) as raised:
        async with stream_text(SITE, "small", "x", decoding=DECODING, max_attempts=1) as pieces:
            [piece async for piece in pieces]
    assert raised.value.kind is ModelFailureKind.UNAVAILABLE and failures == [(SITE.value, "unavailable")]

    provider(_response(200, GOOD, "text/event-stream"))
    with pytest.raises(KeyError):
        async with stream_text(SITE, "small", "x", decoding=DECODING, max_attempts=1) as pieces:
            async for _piece in pieces:
                raise KeyError("the consumer failed")
    assert len(failures) == 1


async def test_a_request_without_a_recording_reaches_the_test_and_is_not_a_model_failure(failures) -> None:
    """A replay for a request that has no recording is a test error: a call site must not turn it into `unavailable`."""
    # The real class needs a cassette to be built; the replay test of `test_agent_replay.py` raises the real one.
    refused = type("CannotOverwriteExistingCassetteException", (Exception,), {})("no recording")
    assert agent_module._wrap(SITE, refused) is refused and failures == []
    assert isinstance(agent_module._wrap(SITE, RuntimeError("something else")), ModelCallFailed)
