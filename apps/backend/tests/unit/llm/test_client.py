"""litellm transport + provider resolution (EPIC-023 AC23.2.2, AC23.2.3).

litellm is mocked so these run offline and deterministically — they pin the
wiring (delta streaming, drop_params, seed/extra_body passthrough, error
normalisation, provider resolution), not litellm's own behaviour.
"""

from __future__ import annotations

import pytest

import src.llm.client as client_mod
from src.llm.client import litellm_stream, resolve_provider_and_model
from src.llm.common import LLMConfigError, LLMError, ProtocolFamily, ProviderRef


class _Delta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.delta = _Delta(content)
        self.message = _Delta(content)
        self.finish_reason = None


class _Chunk:
    def __init__(self, content: str | None) -> None:
        self.choices = [_Choice(content)]


def _provider() -> ProviderRef:
    return ProviderRef(
        id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k", api_base="https://api.z.ai"
    )


@pytest.fixture
def captured(monkeypatch):
    """Patch litellm.acompletion; capture kwargs and serve canned chunks."""
    box: dict = {}

    async def fake_acompletion(**kwargs):
        box["kwargs"] = kwargs

        async def gen():
            for piece in ("Hel", "", "lo"):
                yield _Chunk(piece)

        return gen()

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    return box


async def test_AC23_2_2_stream_yields_only_nonempty_deltas(captured):
    """AC23.2.2: litellm_stream yields content deltas, skipping empty ones."""
    out = [
        c async for c in litellm_stream([{"role": "user", "content": "hi"}], provider=_provider(), model_id="glm-5.1")
    ]
    assert "".join(out) == "Hello"


async def test_AC23_2_2_stream_sets_drop_params_and_passes_seed_extra_body(captured):
    """AC23.2.2: drop_params is on; seed is native; Z.AI knobs ride extra_body."""
    async for _ in litellm_stream(
        [{"role": "user", "content": "hi"}],
        provider=_provider(),
        model_id="glm-5.1",
        seed=7,
        extra_body={"do_sample": False, "thinking": {"type": "disabled"}},
    ):
        pass
    kw = captured["kwargs"]
    assert kw["drop_params"] is True
    assert kw["stream"] is True
    assert kw["seed"] == 7
    assert kw["extra_body"] == {"do_sample": False, "thinking": {"type": "disabled"}}
    assert kw["model"] == "openai/glm-5.1"
    assert kw["api_base"] == "https://api.z.ai"


async def test_AC23_2_4_reasoning_max_tokens_temperature_passthrough(captured):
    """AC23.2.4: per-scene knobs (reasoning depth, max_tokens, temperature) reach litellm."""
    from src.llm.common import ReasoningEffort

    async for _ in litellm_stream(
        [{"role": "user", "content": "hi"}],
        provider=_provider(),
        model_id="glm-5.1",
        max_tokens=256,
        temperature=0.0,
        reasoning=ReasoningEffort.MEDIUM,
    ):
        pass
    kw = captured["kwargs"]
    assert kw["max_tokens"] == 256
    assert kw["temperature"] == 0.0
    assert kw["reasoning_effort"] == "medium"


async def test_AC23_2_3_provider_error_is_normalised_to_llmerror(monkeypatch):
    """AC23.2.3: a transient provider failure becomes a retryable LLMError."""

    class RateLimitError(Exception):
        pass

    async def boom(**kwargs):
        raise RateLimitError("429 slow down")

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)

    with pytest.raises(LLMError) as ei:
        async for _ in litellm_stream([{"role": "user", "content": "x"}], provider=_provider(), model_id="m"):
            pass
    assert ei.value.retryable is True


async def test_AC23_2_3_non_retryable_error_classified(monkeypatch):
    """AC23.2.3: an unknown provider error is wrapped as non-retryable."""

    async def boom(**kwargs):
        raise ValueError("bad request")

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    with pytest.raises(LLMError) as ei:
        async for _ in litellm_stream([{"role": "user", "content": "x"}], provider=_provider(), model_id="m"):
            pass
    assert ei.value.retryable is False


class _FakeConfig:
    def __init__(self, providers: list[ProviderRef]) -> None:
        self._providers = providers

    async def list_providers(self):
        return list(self._providers)

    async def get_provider(self, provider_id):
        return next((p for p in self._providers if p.id == provider_id), None)


async def test_AC23_2_2_resolves_provider_from_qualified_model():
    """AC23.2.2: a 'provider_id/model' binding selects that provider among several."""
    p_zai = _provider()
    p_or = ProviderRef(id="router", label="or", protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key="k2")
    provider, model = await resolve_provider_and_model(_FakeConfig([p_zai, p_or]), "router/deepseek-chat")
    assert provider is p_or
    assert model == "deepseek-chat"


async def test_AC23_2_2_ambiguous_unqualified_model_with_many_providers_errors():
    """AC23.2.2: an unqualified model with >1 provider is rejected, not guessed."""
    p1 = _provider()
    p2 = ProviderRef(id="other", label="o", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k2")
    with pytest.raises(LLMConfigError):
        await resolve_provider_and_model(_FakeConfig([p1, p2]), "glm-5.1")


async def test_AC23_2_2_no_provider_configured_errors():
    """AC23.2.2: resolving with zero providers is a config error."""
    with pytest.raises(LLMConfigError):
        await resolve_provider_and_model(_FakeConfig([]), "glm-5.1")


async def test_AC23_2_2_unknown_qualified_provider_raises_not_silently_falls_back():
    """AC23.2.2: a provider_id-qualified model whose provider is unknown raises, not silently wrong creds."""
    p1 = _provider()
    p2 = ProviderRef(id="other", label="o", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k2")
    with pytest.raises(LLMConfigError):
        await resolve_provider_and_model(_FakeConfig([p1, p2]), "ghost/model")


async def test_AC23_2_2_single_provider_honours_db_style_qualified_binding():
    """AC23.2.2: a DB binding qualified as provider_id/model strips the id even with one provider."""
    p = ProviderRef(id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k", api_base="https://z")
    provider, model = await resolve_provider_and_model(_FakeConfig([p]), "env/glm-5.1")
    assert provider is p
    assert model == "glm-5.1"


async def test_AC23_2_2_single_provider_keeps_slashed_openrouter_model():
    """AC23.2.2: with one provider an OpenRouter vendor/model id is used whole, not split as provider."""
    p = ProviderRef(id="env", label="or", protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key="k")
    provider, model = await resolve_provider_and_model(_FakeConfig([p]), "deepseek/deepseek-chat")
    assert provider is p
    assert model == "deepseek/deepseek-chat"
