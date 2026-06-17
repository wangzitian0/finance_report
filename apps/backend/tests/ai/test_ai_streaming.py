"""ai_streaming delegates to litellm (EPIC-023 PR3 cutover).

The old httpx/SSE transport is gone; these tests pin the litellm delegation:
provider resolution (explicit creds vs configured default), JSON/chat streaming,
Z.AI knob passthrough, and error normalisation. litellm is mocked so they run
offline. (The litellm transport itself is covered by tests/unit/llm/test_client.py.)
"""

from __future__ import annotations

import pytest

import src.llm.client as client_mod
import src.services.ai_streaming as ai_streaming
from src.config import settings
from src.llm.common import ProtocolFamily, ProviderRef
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
    """AC13.16.1: a provided seed is forwarded in the request payload (deterministic
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


async def test_AC23_4_7_budget_exceeded_blocks_live_stream(litellm_stub, monkeypatch):
    """AC23.4.7: the live transport enforces the daily ceiling — once today's spend
    reaches the limit, a stream is refused (non-retryable) instead of calling out."""
    from decimal import Decimal

    from src.llm.cost import DailyBudgetMeter, _utc_today

    meter = DailyBudgetMeter(Decimal("1"))
    meter._day = _utc_today()  # pin today so the rollover doesn't reset spent
    meter._spent = Decimal("5")  # already over the daily limit
    monkeypatch.setattr(ai_streaming, "get_budget_meter", lambda: meter)

    with pytest.raises(AIStreamError) as ei:
        await accumulate_stream(stream_ai_chat([{"role": "user", "content": "x"}], "glm-5.1", api_key="k"))
    assert "budget" in str(ei.value).lower()
    assert ei.value.retryable is False


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
