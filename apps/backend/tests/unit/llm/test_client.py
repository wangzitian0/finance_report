"""litellm transport + scene client (EPIC-023 AC23.2.2, AC23.2.3).

litellm is mocked so these run offline and deterministically — they pin the
wiring (delta streaming, drop_params, seed/extra_body passthrough, error
normalisation, scene resolution), not litellm's own behaviour.
"""

from __future__ import annotations

import pytest

import src.llm.client as client_mod
from src.llm.client import LitellmClient, litellm_complete, litellm_stream
from src.llm.common import LLMConfigError, LLMError, ProtocolFamily, ProviderRef, Scene, SceneBinding


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


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5


class _Response:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]
        self.usage = _Usage()


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
        if kwargs.get("stream"):

            async def gen():
                for piece in ("Hel", "", "lo"):
                    yield _Chunk(piece)

            return gen()
        return _Response("Hello")

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(client_mod.litellm, "completion_cost", lambda completion_response=None: 0.0012)
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


async def test_AC23_2_2_complete_returns_text_usage_and_cost(captured):
    """AC23.2.2: litellm_complete maps text + token usage + USD cost."""
    result = await litellm_complete([{"role": "user", "content": "hi"}], provider=_provider(), model_id="glm-5.1")
    assert result.text == "Hello"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5
    assert result.usage.total_tokens == 15
    assert str(result.cost_usd) == "0.0012"


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


async def test_AC23_2_2_complete_handles_empty_response_and_missing_cost(monkeypatch):
    """AC23.2.2: a response with no choices/usage yields empty text + zero usage; cost stays None."""

    class _Empty:
        choices: list = []
        usage = None

    async def fake(**kwargs):
        return _Empty()

    def boom_cost(completion_response=None):
        raise RuntimeError("no pricing")

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake)
    monkeypatch.setattr(client_mod.litellm, "completion_cost", boom_cost)
    result = await litellm_complete([{"role": "user", "content": "x"}], provider=_provider(), model_id="m")
    assert result.text == ""
    assert result.usage.total_tokens == 0
    assert result.cost_usd is None


async def test_AC23_2_2_complete_without_cost_meter(captured):
    """AC23.2.2: a client without a cost meter still completes (no budget hooks)."""
    cfg = _FakeConfig(SceneBinding(Scene.STATEMENT_SUMMARY, "glm-5.1"), [_provider()])
    result = await LitellmClient(cfg).complete(Scene.STATEMENT_SUMMARY, [{"role": "user", "content": "hi"}])
    assert result.text == "Hello"


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
        await litellm_complete([{"role": "user", "content": "x"}], provider=_provider(), model_id="m")
    assert ei.value.retryable is False


class _FakeConfig:
    def __init__(self, binding: SceneBinding | None, providers: list[ProviderRef]) -> None:
        self._binding = binding
        self._providers = providers

    async def list_providers(self):
        return list(self._providers)

    async def get_provider(self, provider_id):
        return next((p for p in self._providers if p.id == provider_id), None)

    async def get_binding(self, scene):
        return self._binding

    async def is_configured(self):
        return bool(self._providers)


async def test_AC23_2_2_scene_client_resolves_binding_and_streams(captured):
    """AC23.2.2: LitellmClient resolves a scene's binding through the ConfigSource."""
    cfg = _FakeConfig(SceneBinding(Scene.ADVISOR_CHAT, "glm-5.1"), [_provider()])
    cli = LitellmClient(cfg)
    out = [c async for c in cli.stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}])]
    assert "".join(out) == "Hello"


async def test_AC23_2_2_scene_client_stream_json_path(captured):
    """AC23.2.2: stream_json resolves a scene and streams (prompt-driven JSON, no response_format)."""
    cfg = _FakeConfig(SceneBinding(Scene.EXTRACTION_JSON, "glm-4.6v"), [_provider()])
    out = [c async for c in LitellmClient(cfg).stream_json(Scene.EXTRACTION_JSON, [{"role": "user", "content": "x"}])]
    assert "".join(out) == "Hello"
    assert "response_format" not in captured["kwargs"]


async def test_AC23_2_2_cost_is_none_when_litellm_returns_none(monkeypatch):
    """AC23.2.2: a None cost from litellm surfaces as None (no spurious zero)."""
    box: dict = {}

    async def fake(**kwargs):
        box["k"] = kwargs
        return _Response("Hi")

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake)
    monkeypatch.setattr(client_mod.litellm, "completion_cost", lambda completion_response=None: None)
    result = await litellm_complete([{"role": "user", "content": "x"}], provider=_provider(), model_id="m")
    assert result.cost_usd is None


async def test_AC23_2_2_scene_client_raises_when_scene_unbound(captured):
    """AC23.2.2: an unbound scene is a config error, not a silent no-op."""
    cli = LitellmClient(_FakeConfig(None, [_provider()]))
    with pytest.raises(LLMConfigError):
        async for _ in cli.stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}]):
            pass


async def test_AC23_2_2_scene_client_complete_records_cost(captured):
    """AC23.2.2 / AC23.2.6: complete() runs the budget check and records spend via the meter."""
    events: list[tuple] = []

    class _Meter:
        async def check_budget(self):
            events.append(("check",))

        async def record(self, scene, model_id, usage, cost_usd):
            events.append(("record", scene, model_id, str(cost_usd)))

    cfg = _FakeConfig(SceneBinding(Scene.ADVISOR_CHAT, "glm-5.1"), [_provider()])
    cli = LitellmClient(cfg, cost_meter=_Meter())
    result = await cli.complete(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}])
    assert result.text == "Hello"
    assert ("check",) in events
    assert any(e[0] == "record" for e in events)


async def test_AC23_2_2_resolves_provider_from_qualified_model(captured):
    """AC23.2.2: a 'provider_id/model' binding selects that provider among several."""
    p_zai = _provider()
    p_or = ProviderRef(id="router", label="or", protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key="k2")
    cfg = _FakeConfig(SceneBinding(Scene.ADVISOR_CHAT, "router/deepseek-chat"), [p_zai, p_or])
    cli = LitellmClient(cfg)
    async for _ in cli.stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}]):
        pass
    assert captured["kwargs"]["model"] == "openrouter/deepseek-chat"


async def test_AC23_2_2_ambiguous_unqualified_model_with_many_providers_errors(captured):
    """AC23.2.2: an unqualified model with >1 provider is rejected, not guessed."""
    p1 = _provider()
    p2 = ProviderRef(id="other", label="o", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k2")
    cli = LitellmClient(_FakeConfig(SceneBinding(Scene.ADVISOR_CHAT, "glm-5.1"), [p1, p2]))
    with pytest.raises(LLMConfigError):
        async for _ in cli.stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}]):
            pass


async def test_AC23_2_2_no_provider_configured_errors(captured):
    """AC23.2.2: streaming with zero providers is a config error."""
    cli = LitellmClient(_FakeConfig(SceneBinding(Scene.ADVISOR_CHAT, "glm-5.1"), []))
    with pytest.raises(LLMConfigError):
        async for _ in cli.stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}]):
            pass


async def test_AC23_2_2_unknown_qualified_provider_raises_not_silently_falls_back(captured):
    """AC23.2.2: a provider_id-qualified model whose provider is unknown raises, not silently wrong creds."""
    p1 = _provider()
    p2 = ProviderRef(id="other", label="o", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k2")
    cli = LitellmClient(_FakeConfig(SceneBinding(Scene.ADVISOR_CHAT, "ghost/model"), [p1, p2]))
    with pytest.raises(LLMConfigError):
        async for _ in cli.stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}]):
            pass


async def test_AC23_2_2_single_provider_honours_db_style_qualified_binding(captured):
    """AC23.2.2: a DB binding qualified as provider_id/model strips the id even with one provider."""
    p = ProviderRef(id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k", api_base="https://z")
    cfg = _FakeConfig(SceneBinding(Scene.EXTRACTION_JSON, "env/glm-5.1"), [p])
    async for _ in LitellmClient(cfg).stream(Scene.EXTRACTION_JSON, [{"role": "user", "content": "x"}]):
        pass
    assert captured["kwargs"]["model"] == "openai/glm-5.1"


async def test_AC23_2_2_single_provider_keeps_slashed_openrouter_model(captured):
    """AC23.2.2: with one provider an OpenRouter vendor/model id is used whole, not split as provider."""
    p = ProviderRef(id="env", label="or", protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key="k")
    cfg = _FakeConfig(SceneBinding(Scene.ADVISOR_CHAT, "deepseek/deepseek-chat"), [p])
    async for _ in LitellmClient(cfg).stream(Scene.ADVISOR_CHAT, [{"role": "user", "content": "hi"}]):
        pass
    assert captured["kwargs"]["model"] == "openrouter/deepseek/deepseek-chat"
