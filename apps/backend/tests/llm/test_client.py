from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import litellm
import pytest
from litellm.utils import get_optional_params

import src.llm.extension.client as client_mod
from src.llm.base import DecodeParams, LLMConfigError, LLMError, ProtocolFamily, ProviderRef, ReasoningEffort
from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore
from src.llm.extension.client import cassette_completion, litellm_stream
from tests.llm.conftest import StreamChunk, explode_litellm, zai_provider


@pytest.fixture(autouse=True)
def _live_transport(monkeypatch):
    monkeypatch.setenv("LLM_LIVE", "1")


@pytest.fixture
def captured(monkeypatch):
    box: dict = {}

    async def fake_acompletion(**kwargs):
        box["kwargs"] = kwargs

        async def gen():
            for piece in ("Hel", "", "lo"):
                yield StreamChunk(piece)

        return gen()

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    return box


async def _collect(model_id: str = "glm-5.1", provider: ProviderRef | None = None, decode: DecodeParams | None = None) -> str:
    return "".join([c async for c in litellm_stream([{"role": "user", "content": "hi"}], provider=provider or zai_provider(), model_id=model_id, decode=decode or DecodeParams())])


async def test_stream_decode_params_and_provider_knobs(captured) -> None:
    assert await _collect(decode=DecodeParams(seed=7, max_tokens=256, temperature=0.0, reasoning=ReasoningEffort.MEDIUM, extra_body={"do_sample": False, "thinking": {"type": "disabled"}})) == "Hello"
    kw = captured["kwargs"]
    assert (kw["drop_params"], kw["stream"], kw["seed"], kw["max_tokens"], kw["temperature"], kw["reasoning_effort"], kw["model"], kw["api_base"], kw["extra_body"]) == (
        True, True, 7, 256, 0.0, "medium", "openai/glm-5.1", "https://api.z.ai", {"do_sample": False, "thinking": {"type": "disabled"}},
    )
    await _collect()
    assert "reasoning_effort" not in captured["kwargs"]
    await _collect(model_id="gemini-3-flash-preview", provider=ProviderRef(id="env", label="gemini", protocol=ProtocolFamily.GOOGLE_GEMINI, api_key="k"))
    assert (captured["kwargs"]["reasoning_effort"], captured["kwargs"]["model"], captured["kwargs"].get("api_base")) == ("disable", "gemini/gemini-3-flash-preview", None)


@pytest.mark.no_db
@pytest.mark.parametrize("model_id", ["glm-5.3", "glm-5.3-flash", "openai/GLM-5.3-Flash", "glm-5.3-flashx", "openai/GLM-5.3-FlashX"])
@pytest.mark.parametrize(("reasoning", "expected"), [(None, "low"), (ReasoningEffort.NONE, "low"), (ReasoningEffort.LOW, "low"), (ReasoningEffort.MEDIUM, "high"), (ReasoningEffort.HIGH, "high")])
async def test_glm53_stream_uses_supported_reasoning_parameters(captured, model_id, reasoning, expected) -> None:
    extra_body = {"do_sample": False, "thinking": {"type": "disabled", "clear_thinking": False}}
    decode = DecodeParams(reasoning=reasoning, extra_body=extra_body, max_tokens=8192)
    result = await _collect(model_id=model_id, decode=decode)
    wire = captured["kwargs"]
    forwarded = get_optional_params(model=model_id.removeprefix("openai/"), custom_llm_provider="openai", reasoning_effort=wire["reasoning_effort"], drop_params=wire["drop_params"], allowed_openai_params=wire.get("allowed_openai_params"))
    assert (result, wire["extra_body"]["thinking"], wire["reasoning_effort"], forwarded["reasoning_effort"], wire["extra_body"]["do_sample"], wire["max_tokens"], decode.extra_body["thinking"]["type"], extra_body["thinking"]["type"]) == (
        "Hello", {"type": "enabled", "clear_thinking": False}, expected, expected, False, 8192, "disabled", "disabled",
    )


@pytest.mark.no_db
async def test_glm53_without_decode_options_uses_bounded_reasoning(captured) -> None:
    await _collect(model_id="glm-5.3")
    assert (captured["kwargs"]["extra_body"]["thinking"], captured["kwargs"]["reasoning_effort"]) == ({"type": "enabled"}, "low")


@pytest.mark.parametrize(("exc_factory", "expected_retryable"), [(lambda: type("RateLimitError", (Exception,), {})("429 slow down"), True), (lambda: ValueError("bad request"), False)])
async def test_AC23_2_3_provider_error_normalised_to_llmerror(monkeypatch, exc_factory, expected_retryable: bool) -> None:
    async def boom(**_kwargs):
        raise exc_factory()

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    with pytest.raises(LLMError) as ei:
        await _collect(model_id="m")
    assert ei.value.retryable is expected_retryable


async def test_AC23_5_4_cassette_completion_modes_and_decode(monkeypatch, tmp_path) -> None:
    store, captured_kwargs = CassetteStore(directory=tmp_path / "c"), {}
    resp = SimpleNamespace(model_dump=lambda: {"text": "frozen"})

    async def fake_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return resp

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    msgs = [{"role": "user", "content": "balance?"}]
    off_out = await cassette_completion(msgs, role="advisor.chat", provider=zai_provider(), model_id="glm-5.1", recorder=CassetteRecorder(store, mode=CassetteMode.OFF), decode=DecodeParams(temperature=0.0, max_tokens=16))
    rec_out = await cassette_completion(msgs, role="extraction.json", provider=zai_provider(), model_id="glm-5.1", recorder=CassetteRecorder(store, mode=CassetteMode.RECORD), decode=DecodeParams(temperature=0.0))
    monkeypatch.setattr(client_mod.litellm, "acompletion", explode_litellm)
    play_out = await cassette_completion(msgs, role="extraction.json", provider=zai_provider(), model_id="glm-5.2", recorder=CassetteRecorder(store, mode=CassetteMode.REPLAY), decode=DecodeParams(temperature=0.0))
    assert off_out == rec_out == play_out == {"text": "frozen"}

    for raw_ret, expected in (({"plain": "dict"}, {"plain": "dict"}), (12345, {"text": "12345"})):
        captured_kwargs.clear()
        monkeypatch.setattr(client_mod.litellm, "acompletion", lambda *_a, _r=raw_ret, **kw: (captured_kwargs.update(kw) or SimpleNamespace(__await__=lambda _s: iter(()))) if False else _aret_kw(captured_kwargs, kw, _r))
        out = await cassette_completion([{"role": "user", "content": f"hi-{raw_ret}"}], role="extraction.vision", provider=zai_provider(), model_id="test-vision-model", recorder=CassetteRecorder(store, mode=CassetteMode.RECORD), decode=DecodeParams(reasoning=ReasoningEffort.MEDIUM, seed=11, extra_body={"thinking": {"type": "disabled"}}), timeout=5.0)
        assert (out, captured_kwargs["reasoning_effort"], captured_kwargs["seed"], captured_kwargs["timeout"]) == (expected, "medium", 11, 5.0)


async def _aret_kw(box: dict, kw: dict, val):
    box.update(kw)
    return val


@pytest.mark.parametrize("raised", [ValueError("bad request"), LLMError("already normalised", retryable=True)])
async def test_AC23_5_4_cassette_completion_error_wrapping(monkeypatch, tmp_path, raised: Exception) -> None:
    async def boom(**_kwargs):
        raise raised

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    with pytest.raises(LLMError) as ei:
        await cassette_completion([{"role": "user", "content": "x"}], role="advisor.chat", provider=zai_provider(), model_id="m", recorder=CassetteRecorder(CassetteStore(directory=tmp_path / "c"), mode=CassetteMode.RECORD))
    assert ei.value.retryable is isinstance(raised, LLMError)


def test_AC23_9_1_and_wrap_redaction() -> None:
    assert client_mod.litellm.disable_aiohttp_transport is True and litellm.disable_aiohttp_transport is True

    class _ProviderError(Exception):
        def __init__(self, msg: str, status_code=None):
            super().__init__(msg)
            self.status_code = status_code

    RateLimitError = type("RateLimitError", (_ProviderError,), {})
    secret = "key sk-SECRET-123 at https://open.bigmodel.cn/api/paas/v4/chat Authorization: Bearer abc"
    for text in (
        f"Error code: 429 - {{'error': {{'code': '1113', 'message': 'Insufficient balance. {secret}'}}}}",
        f'{{"error":{{"code":"1113","message":"Insufficient balance. {secret}"}}}}',
        f"Error code: 429 - {{'error': {{'code': 1113, 'message': '{secret}'}}}}",
    ):
        err = client_mod._wrap(RateLimitError(text, status_code=429))
        assert str(err) == "LLM provider call failed (RateLimitError, http 429, provider code 1113)" and err.retryable is True
        assert all(leaked not in str(err) for leaked in ("sk-SECRET", "Bearer", "https://", "Insufficient"))

    assert str(client_mod._wrap(ValueError("bad request"))) == "LLM provider call failed (ValueError)"
    assert str(client_mod._wrap(_ProviderError('{"error":{"code":"rate_limited"}}', status_code=429))) == "LLM provider call failed (_ProviderError, http 429)"
    for bad_status in ("429", True, 99, 600):
        assert str(client_mod._wrap(_ProviderError("x", status_code=bad_status))) == "LLM provider call failed (_ProviderError)"


@pytest.fixture
def provider_429():
    state: dict = {"body": {}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            raw = json.dumps(state["body"]).encode()
            self.send_response(429)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        log_message = lambda *_a: None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield (state, ProviderRef(id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k", api_base=f"http://127.0.0.1:{server.server_port}/v1"))
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"error": {"code": "1302", "message": "Rate limit reached for requests"}}, "provider code 1302"),
        ({"error": {"code": 1113, "message": "key sk-SECRET-123 at https://x.example/v1 Bearer abc"}}, "provider code 1113"),
        ({"code": 1305, "msg": "too many requests", "success": False}, "provider code 1305"),
        ({"error": {"code": "rate_limited", "message": "slow down"}}, None),
        ({"error": {"message": "slow down"}}, None),
    ],
)
async def test_AC_llm_provider_error_code_1_real_429_body(provider_429, body, expected) -> None:
    state, provider = provider_429
    state["body"] = body
    with pytest.raises(LLMError) as ei:
        await _collect(model_id="glm-5.3-flashx", provider=provider)
    want = "LLM provider call failed (RateLimitError, http 429" + (f", {expected}" if expected else "") + ")"
    assert (str(ei.value), ei.value.retryable) == (want, True) and all(leaked not in str(ei.value) for leaked in ("sk-SECRET", "Bearer", "https://"))


@pytest.mark.parametrize(("model_id", "adapted"), [("glm-5.3", True), ("glm-5.3-flash", True), ("openai/GLM-5.3-FlashX", True), ("glm-5.3-turbo", True), ("glm-5.2", False), ("glm-5.3-flash-extra", False), ("gpt-4o", False)])
def test_glm53_adapter_applies_by_model_family(model_id: str, adapted: bool) -> None:
    kwargs = client_mod._base_kwargs(provider=zai_provider(), model_id=model_id, messages=[{"role": "user", "content": "x"}], decode=DecodeParams(reasoning=ReasoningEffort.NONE, extra_body={"thinking": {"type": "disabled"}}))
    assert ((kwargs["extra_body"]["thinking"]["type"] == "enabled"), ("allowed_openai_params" in kwargs)) == (adapted, adapted)
