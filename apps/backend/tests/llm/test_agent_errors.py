"""The error contract of the entry point: each failure leaves as one `ModelCallFailed` and is counted once (#3153).

The real SDK model runs here. Only the transport (`httpx2.AsyncClient.send`) is replaced, so the kinds are those of
what the SDK really does with a provider answer, not of a fake.
"""

import asyncio
import copy
import json
import pickle

import httpx2
import pytest
from infra2_sdk.llm import DecodingSpec, allow_vcr_model_requests
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelHTTPError,
    ModelQuotaExceededError,
    OutputTokenLimitExceeded,
    UnexpectedModelBehavior,
    UserError,
)
from pydantic_ai.usage import UsageLimits

import src.llm.extension.agent as agent_module
from src.config import settings
from src.llm import ModelCallFailed, ModelFailureKind
from src.llm.extension.agent import CallSite, complete_text, stream_text

SITE = CallSite.RECONCILIATION_SEMANTIC_SCORE
DECODING = DecodingSpec(decoding_version="test.v1", thinking=False, timeout=5.0)
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


def _text_chunk(content: str, finish_reason: str | None = None) -> dict:
    return {
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": finish_reason}]
    }


# Review of #3194, round 4: a 200 answer with no text is a reply that the provider gave and we cannot use.
EMPTY_REPLIES = [
    ("empty content, finish stop", _sse(_text_chunk("", "stop"))),
    ("no choices", _sse({"choices": []})),
    (
        "reasoning only",
        _sse({"choices": [{"index": 0, "delta": {"reasoning_content": "thinking"}, "finish_reason": "stop"}]}),
    ),
    ("cut by the token limit, no text", _sse(_text_chunk("", "length"))),
    ("content filter, no text", _sse(_text_chunk("", "content_filter"))),
]


@pytest.mark.parametrize(("name", "body"), EMPTY_REPLIES, ids=[case[0] for case in EMPTY_REPLIES])
async def test_a_reply_without_text_is_a_bad_reply_and_a_warning_not_an_unclassified_error(
    name, body, provider, failures, monkeypatch
) -> None:
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
    provider(_response(200, body, "text/event-stream"))
    with pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1)
    assert raised.value.kind is ModelFailureKind.BAD_REPLY
    assert failures == [(SITE.value, "bad_reply")] and logged == [("warning", "bad_reply")]


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (UserError("bad use"), ModelFailureKind.NOT_CONFIGURED),
        (ModelQuotaExceededError("m", "quota"), ModelFailureKind.RATE_LIMIT),
        (ModelHTTPError(status_code=429, model_name="m", body="x"), ModelFailureKind.RATE_LIMIT),
        (ModelHTTPError(status_code=500, model_name="m", body="x"), ModelFailureKind.UNAVAILABLE),
        (ModelHTTPError(status_code=499, model_name="m", body="x"), ModelFailureKind.REJECTED),
        (UnexpectedModelBehavior("no text"), ModelFailureKind.BAD_REPLY),
        (ContentFilterError("filtered"), ModelFailureKind.BAD_REPLY),
        (OutputTokenLimitExceeded("cut"), ModelFailureKind.BAD_REPLY),
        (RuntimeError("UnexpectedModelBehavior (http=none, provider_code=none)"), ModelFailureKind.BAD_REPLY),
        (RuntimeError("AssertionError (http=none, provider_code=none)"), ModelFailureKind.UNCLASSIFIED),
    ],
    ids=lambda value: value.value if isinstance(value, ModelFailureKind) else type(value).__name__,
)
def test_the_kind_of_an_sdk_error_follows_its_class_and_status(error, kind) -> None:
    assert agent_module._kind_of(error) is kind


def test_each_kind_has_its_http_status_and_retry_flag() -> None:
    expected = {
        ModelFailureKind.RATE_LIMIT: (429, True),
        ModelFailureKind.TIMEOUT: (504, True),
        ModelFailureKind.UNAVAILABLE: (503, True),
        ModelFailureKind.REJECTED: (502, False),
        ModelFailureKind.USAGE_LIMIT: (429, False),
        ModelFailureKind.NOT_CONFIGURED: (503, False),
        ModelFailureKind.BAD_REPLY: (502, False),
        ModelFailureKind.UNCLASSIFIED: (502, False),
    }
    assert set(expected) == set(ModelFailureKind)
    for kind, (status, retryable) in expected.items():
        error = ModelCallFailed(kind, "summary")
        assert (error.status_code, error.retryable) == (status, retryable), kind


def test_the_error_survives_copy_and_pickle() -> None:
    error = ModelCallFailed(ModelFailureKind.RATE_LIMIT, "ModelRateLimitError (http=429)", call_site=SITE.value)
    for clone in (copy.copy(error), copy.deepcopy(error), pickle.loads(pickle.dumps(error))):
        assert (clone.kind, clone.summary, clone.call_site, clone.status_code, clone.retryable) == (
            ModelFailureKind.RATE_LIMIT,
            "ModelRateLimitError (http=429)",
            SITE.value,
            429,
            True,
        )
        assert str(clone) == str(error)


@pytest.mark.parametrize("field", ["ai_base_url", "small_model"])
async def test_a_bad_llm_setting_is_not_configured_and_not_a_raw_value_error(field, monkeypatch, failures) -> None:
    """Review of #3194, round 4: an empty base URL or model made `execute_matching` fail with a bare `ValueError`."""
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, field, "")
    with allow_vcr_model_requests(), pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING)
    assert raised.value.kind is ModelFailureKind.NOT_CONFIGURED and failures == [(SITE.value, "not_configured")]


async def test_a_malformed_content_part_is_an_error_of_the_caller_in_both_entry_points(fake_llm, failures) -> None:
    """Review of #3194, round 4: `complete_text` counted it as `unclassified`, `stream_text` raised it."""
    fake_llm("x")
    with pytest.raises(ValueError, match="Unsupported content part"):
        await complete_text(SITE, "small", [{"type": "bogus"}], decoding=DECODING)
    with pytest.raises(ValueError, match="Unsupported content part"):
        async with stream_text(SITE, "small", [{"type": "bogus"}], decoding=DECODING):
            pass
    assert failures == []


class _StreamThatBreaks(httpx2.AsyncByteStream):
    """The answer starts, and then the connection fails."""

    async def __aiter__(self):
        yield _sse(_text_chunk("hel"), done=False)
        raise httpx2.ReadError("connection reset by peer")


def _broken_stream(request):
    return httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, stream=_StreamThatBreaks(), request=request
    )


async def test_a_failure_after_the_first_chunk_leaves_as_one_error_in_both_entry_points(provider, failures) -> None:
    provider(_broken_stream)
    with pytest.raises(ModelCallFailed) as raised:
        await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1)
    assert raised.value.kind is ModelFailureKind.UNAVAILABLE and failures == [(SITE.value, "unavailable")]

    seen: list[str] = []
    with pytest.raises(ModelCallFailed) as raised_stream:
        async with stream_text(SITE, "small", "x", decoding=DECODING, max_attempts=1) as pieces:
            async for piece in pieces:
                seen.append(piece)
    assert raised_stream.value.kind is ModelFailureKind.UNAVAILABLE
    assert failures == [(SITE.value, "unavailable")] * 2 and "".join(seen) in ("", "hel")


async def test_the_failure_counter_reaches_the_metric_with_its_labels(provider, monkeypatch) -> None:
    """The real counter, not the fixture: a wrong key or name in `telemetry_metrics` would count nothing."""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    from src.observability import telemetry_metrics

    reader = InMemoryMetricReader()
    monkeypatch.setattr(telemetry_metrics, "_instruments", {})
    telemetry_metrics._create_instruments(MeterProvider(metric_readers=[reader]).get_meter("test"))
    provider(_response(429, b"{}"))
    with pytest.raises(ModelCallFailed):
        await complete_text(SITE, "small", "x", decoding=DECODING, max_attempts=1)
    points = [
        (metric.name, dict(point.attributes), point.value)
        for resource in reader.get_metrics_data().resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
        if metric.name == "finance.llm.call.failed"
    ]
    assert points == [("finance.llm.call.failed", {"call_site": SITE.value, "kind": "rate_limit"}, 1)]


def test_the_summary_of_a_failure_is_bounded(failures) -> None:
    """A content-filter error carries the body of the answer: the summary that reaches a log or an HTTP detail is short."""
    error = agent_module._wrap(SITE, ContentFilterError("x" * 2000))
    assert error.kind is ModelFailureKind.BAD_REPLY and len(error.summary) == 300
    assert len(str(error)) < 400
