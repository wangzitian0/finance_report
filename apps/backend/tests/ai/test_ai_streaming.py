"""ai_streaming delegates to litellm (EPIC-023 PR3 cutover).

The old httpx/SSE transport is gone; these tests pin the litellm delegation:
provider resolution (explicit creds vs configured default), JSON/chat streaming,
Z.AI knob passthrough, and error normalisation. litellm is mocked so they run
offline. (The litellm transport itself is covered by tests/unit/llm/test_client.py.)
"""

from __future__ import annotations

import pytest

import src.llm.extension.client as client_mod
import src.services.ai_streaming as ai_streaming
from src.config import settings
from src.llm.base import LLMError, ProtocolFamily, ProviderRef
from src.services.ai_streaming import AIStreamError, accumulate_stream, stream_ai_chat, stream_ai_json

pytestmark = pytest.mark.no_db


class _Delta:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.delta = _Delta(c)


class _Chunk:
    def __init__(self, c):
        self.choices = [_Choice(c)]


@pytest.fixture
def litellm_stub(monkeypatch):
    """Capture litellm kwargs and serve canned stream chunks."""
    box: dict = {}

    async def fake_acompletion(**kwargs):
        box["kwargs"] = kwargs

        async def gen():
            for piece in ('{"ok"', ": true}"):
                yield _Chunk(piece)

        return gen()

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    return box


def _explicit_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "zai", raising=False)
    monkeypatch.setattr(settings, "ai_base_url", "https://api.z.ai", raising=False)


async def test_stream_ai_json_uses_explicit_credentials(litellm_stub, monkeypatch):
    """An explicit api_key/base_url routes via litellm with the openai-compatible prefix."""
    _explicit_provider(monkeypatch)
    text = await accumulate_stream(
        stream_ai_json([{"role": "user", "content": "x"}], "glm-4.6v", api_key="sk-explicit")
    )
    assert text == '{"ok": true}'
    kw = litellm_stub["kwargs"]
    assert kw["model"] == "openai/glm-4.6v"
    assert kw["api_base"] == "https://api.z.ai"
    assert kw["drop_params"] is True


async def test_stream_ai_json_forwards_zai_knobs_and_seed(litellm_stub, monkeypatch):
    """AC-extraction.116.1: a provided seed is forwarded in the request payload (deterministic
    decoding, #989). do_sample/thinking ride extra_body; seed is a native (droppable) param."""
    _explicit_provider(monkeypatch)
    await accumulate_stream(
        stream_ai_json(
            [{"role": "user", "content": "x"}],
            "glm-4.6v",
            api_key="k",
            do_sample=False,
            thinking={"type": "disabled"},
            seed=9,
            temperature=0.0,
        )
    )
    kw = litellm_stub["kwargs"]
    assert kw["extra_body"] == {"do_sample": False, "thinking": {"type": "disabled"}}
    assert kw["seed"] == 9
    assert kw["temperature"] == 0.0


async def test_stream_ai_json_drops_glm_knobs_for_gemini(litellm_stub, monkeypatch):
    """do_sample/thinking are Z.AI/GLM extra_body knobs; Gemini rejects unknown request
    fields with HTTP 400. For a Gemini provider they must NOT be forwarded, and the live
    call instead carries reasoning_effort="disable" (Gemini 2.5+ thinks by default and the
    thinking tokens otherwise eat the output budget, truncating a verbose extraction)."""
    monkeypatch.setattr(settings, "ai_provider", "gemini", raising=False)
    await accumulate_stream(
        stream_ai_json(
            [{"role": "user", "content": "x"}],
            "gemini-3-flash-preview",
            api_key="k",
            do_sample=False,
            thinking={"type": "disabled"},
            temperature=0.0,
        )
    )
    kw = litellm_stub["kwargs"]
    assert "extra_body" not in kw  # GLM knobs not forwarded to Gemini
    assert kw.get("reasoning_effort") == "disable"
    assert kw["model"] == "gemini/gemini-3-flash-preview"


async def test_stream_resolves_default_provider_from_config(litellm_stub, monkeypatch):
    """With no explicit key, the configured default provider is resolved."""

    class _Cfg:
        async def list_providers(self):
            return [
                ProviderRef(
                    id="env",
                    label="zai",
                    protocol=ProtocolFamily.OPENAI_COMPATIBLE,
                    api_key="cfg",
                    api_base="https://z",
                )
            ]

    monkeypatch.setattr(ai_streaming, "get_config_source", lambda *_a, **_k: _Cfg())
    text = await accumulate_stream(stream_ai_chat([{"role": "user", "content": "hi"}], "glm-5.1"))
    assert text == '{"ok": true}'
    assert litellm_stub["kwargs"]["model"] == "openai/glm-5.1"


async def test_stream_raises_when_no_provider_configured(monkeypatch):
    """No explicit key and no configured provider -> AIStreamError (not configured)."""

    class _Empty:
        async def list_providers(self):
            return []

    monkeypatch.setattr(ai_streaming, "get_config_source", lambda *_a, **_k: _Empty())
    with pytest.raises(AIStreamError):
        await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "glm-5.1"))


async def test_stream_fails_closed_with_multiple_providers(monkeypatch):
    """Scene-less path can't disambiguate >1 provider -> fail closed (no nondeterministic routing)."""

    class _Multi:
        async def list_providers(self):
            return [
                ProviderRef(id="a", label="a", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k1"),
                ProviderRef(id="b", label="b", protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key="k2"),
            ]

    monkeypatch.setattr(ai_streaming, "get_config_source", lambda *_a, **_k: _Multi())
    with pytest.raises(AIStreamError):
        await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "glm-5.1"))


async def test_AC23_4_7_records_request_and_token_usage(litellm_stub, monkeypatch):
    """AC-llm.4.7: a completed live stream counts one request + (estimated) tokens, and
    never sends stream_options (Z.AI rejects unknown params)."""
    from src.llm.base.usage import LlmUsageMeter

    meter = LlmUsageMeter()
    monkeypatch.setattr(ai_streaming, "get_usage_meter", lambda: meter)

    text = await accumulate_stream(stream_ai_chat([{"role": "user", "content": "hello there"}], "glm-5.1", api_key="k"))
    assert text == '{"ok": true}'
    # one request counted, with some estimated tokens (prompt + completion text).
    assert meter.requests_today == 1
    assert meter.tokens_today > 0
    # the Z.AI-unsafe stream_options must NOT be on the request.
    assert "stream_options" not in litellm_stub["kwargs"]


async def test_AC23_4_5_user_qualified_model_resolves_exact_provider_with_many(litellm_stub, monkeypatch):
    """AC-llm.4.5 / C1: a user with several providers + a qualified binding (provider_id/model)
    resolves the exact provider instead of failing closed."""
    from uuid import uuid4

    prov_a = ProviderRef(
        id="a", label="a", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k1", api_base="https://a"
    )
    prov_b = ProviderRef(
        id="b", label="b", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k2", api_base="https://b"
    )

    class _MultiScoped:
        async def list_providers(self):
            return [prov_a, prov_b]

        async def get_provider(self, provider_id):
            return {"a": prov_a, "b": prov_b}.get(provider_id)

    monkeypatch.setattr(ai_streaming, "get_config_source", lambda *_a, **_k: _MultiScoped())
    # Qualified model "b/glm-4.6" + a real user_id -> provider b is selected, bare model sent.
    text = await accumulate_stream(stream_ai_chat([{"role": "user", "content": "hi"}], "b/glm-4.6", user_id=uuid4()))
    assert text == '{"ok": true}'
    assert litellm_stub["kwargs"]["model"] == "openai/glm-4.6"
    assert litellm_stub["kwargs"]["api_base"] == "https://b"


async def test_litellm_error_becomes_retryable_aistreamerror(monkeypatch):
    """A litellm provider failure surfaces as a retryable AIStreamError."""
    _explicit_provider(monkeypatch)

    class RateLimitError(Exception):
        pass

    async def boom(**kwargs):
        raise RateLimitError("429")

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    with pytest.raises(AIStreamError) as ei:
        await accumulate_stream(stream_ai_chat([{"role": "user", "content": "x"}], "glm-5.1", api_key="k"))
    assert ei.value.retryable is True


async def test_AC10_10_4_ai_provider_call_metric_emitted_on_success(litellm_stub, monkeypatch):
    """AC-observability.10.4: a completed provider stream emits the ai-provider latency metric
    (outcome=success), driven through the real _stream_ai_base path."""
    _explicit_provider(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr(ai_streaming, "record_ai_provider_call", lambda **kw: calls.append(kw))

    text = await accumulate_stream(
        stream_ai_json([{"role": "user", "content": "x"}], "glm-4.6v", api_key="sk-explicit")
    )

    assert text == '{"ok": true}'
    assert len(calls) == 1
    assert calls[0]["outcome"] == "success"
    assert calls[0]["model"] == "glm-4.6v"
    assert calls[0]["duration_ms"] >= 0
    # Label is the bounded protocol family (StrEnum), never the user-editable
    # free-text provider.label — no PII / no unbounded cardinality.
    assert calls[0]["provider"] in {"openai-compatible", "anthropic-compatible", "openrouter-compatible"}


async def test_AC10_10_4_ai_provider_call_metric_emitted_on_error(monkeypatch):
    """AC-observability.10.4: a failed provider stream emits the ai-provider metric (outcome=error)
    and still re-raises AIStreamError."""
    _explicit_provider(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr(ai_streaming, "record_ai_provider_call", lambda **kw: calls.append(kw))

    async def boom_stream(*_a, **_k):
        raise LLMError("provider exploded", retryable=True)
        yield  # pragma: no cover - async-generator marker

    monkeypatch.setattr(ai_streaming, "litellm_stream", lambda *a, **k: boom_stream())

    with pytest.raises(AIStreamError):
        await accumulate_stream(stream_ai_json([{"role": "user", "content": "x"}], "glm-4.6v", api_key="sk-explicit"))

    assert len(calls) == 1
    assert calls[0]["outcome"] == "error"
