from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.llm.extension.client as client_mod
import src.llm.extension.streaming as streaming
from src.config import settings
from src.llm import AIStreamError, accumulate_stream, stream_ai_chat, stream_ai_json
from src.llm.base import LLMError, ProtocolFamily, ProviderRef
from src.llm.base.usage import LlmUsageMeter
from tests.ai.conftest import aret

pytestmark = pytest.mark.no_db
_chunk = lambda c: SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=c))])


@pytest.fixture(autouse=True)
def _force_live_transport(monkeypatch):
    monkeypatch.setenv("LLM_LIVE", "1")


@pytest.fixture
def litellm_stub(monkeypatch):
    box: dict = {}

    async def fake_acompletion(**kwargs):
        box["kwargs"] = kwargs

        async def gen():
            for piece in ('{"ok"', ": true}"):
                yield _chunk(piece)

        return gen()

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    return box


def _explicit_provider(monkeypatch, provider: str = "zai", base_url: str | None = "https://api.z.ai") -> None:
    monkeypatch.setattr(settings, "ai_provider", provider, raising=False)
    if base_url is not None:
        monkeypatch.setattr(settings, "ai_base_url", base_url, raising=False)


async def test_stream_ai_json_provider_knobs_and_credentials(litellm_stub, monkeypatch) -> None:
    _explicit_provider(monkeypatch)
    text = await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "test-vision-model", api_key="sk-explicit", do_sample=False, thinking={"type": "disabled"}, seed=9, temperature=0.0))
    kw = litellm_stub["kwargs"]
    assert (text, kw["model"], kw["api_base"], kw["drop_params"], kw["extra_body"], kw["seed"], kw["temperature"]) == (
        '{"ok": true}', "openai/test-vision-model", "https://api.z.ai", True, {"do_sample": False, "thinking": {"type": "disabled"}}, 9, 0.0,
    )

    _explicit_provider(monkeypatch, provider="gemini", base_url=None)
    await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "gemini-3-flash-preview", api_key="k", do_sample=False, thinking={"type": "disabled"}, temperature=0.0))
    gkw = litellm_stub["kwargs"]
    assert "extra_body" not in gkw and (gkw.get("reasoning_effort"), gkw["model"]) == ("disable", "gemini/gemini-3-flash-preview")


async def test_stream_fails_closed_without_a_configured_provider(monkeypatch) -> None:
    monkeypatch.setattr(streaming, "EnvConfigSource", lambda: SimpleNamespace(list_providers=lambda: aret([])))
    with pytest.raises(AIStreamError):
        await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "glm-5.1"))


async def test_stream_resolves_the_environment_provider_and_usage(litellm_stub, monkeypatch) -> None:
    prov = ProviderRef(id="env", label="env", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k1", api_base="https://a")
    monkeypatch.setattr(streaming, "EnvConfigSource", lambda: SimpleNamespace(list_providers=lambda: aret([prov])))
    assert (await accumulate_stream(stream_ai_chat([{"role": "user", "content": "hi"}], "glm-5.1")), litellm_stub["kwargs"]["model"], litellm_stub["kwargs"]["api_base"]) == (
        '{"ok": true}', "openai/glm-5.1", "https://a",
    )

    meter = LlmUsageMeter()
    monkeypatch.setattr(streaming, "get_usage_meter", lambda: meter)
    await accumulate_stream(stream_ai_chat([{"role": "user", "content": "hello there"}], "glm-5.1", api_key="k"))
    assert meter.requests_today == 1 and meter.tokens_today > 0 and "stream_options" not in litellm_stub["kwargs"]


async def test_litellm_error_and_provider_metrics(litellm_stub, monkeypatch) -> None:
    _explicit_provider(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr(streaming, "record_ai_provider_call", lambda **kw: calls.append(kw))
    text = await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "test-vision-model", api_key="sk-explicit"))
    assert (text, len(calls), calls[0]["outcome"], calls[0]["model"]) == ('{"ok": true}', 1, "success", "test-vision-model")
    assert calls[0]["duration_ms"] >= 0 and calls[0]["provider"] in {"openai-compatible", "anthropic-compatible", "openrouter-compatible"}

    RateLimitError = type("RateLimitError", (Exception,), {})

    async def boom(**_kwargs):
        raise RateLimitError("429")

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    with pytest.raises(AIStreamError) as ei:
        await accumulate_stream(stream_ai_chat([{"role": "user", "content": "x"}], "glm-5.1", api_key="k"))
    assert ei.value.retryable is True

    async def boom_stream(*_a, **_k):
        raise LLMError("provider exploded", retryable=True)
        yield

    monkeypatch.setattr(client_mod, "litellm_stream", lambda *a, **k: boom_stream())
    with pytest.raises(AIStreamError):
        await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "test-vision-model", api_key="sk-explicit"))
    assert len(calls) == 3 and calls[-1]["outcome"] == "error"
