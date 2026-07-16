"""litellm transport + provider resolution (EPIC-023 AC-llm.2.2, AC-llm.2.3).

litellm is mocked so these run offline and deterministically — they pin the
wiring (delta streaming, drop_params, seed/extra_body passthrough, error
normalisation, provider resolution), not litellm's own behaviour.
"""

from __future__ import annotations

import pytest

import src.llm.extension.client as client_mod
from src.llm.base import DecodeParams, LLMConfigError, LLMError, ProtocolFamily, ProviderRef
from src.llm.extension.client import litellm_stream, resolve_provider_and_model


@pytest.fixture(autouse=True)
def _live_transport(monkeypatch):
    """These tests exercise the RAW transport with litellm mocked below it.
    LLM_LIVE is the layer's sanctioned in-layer seam: it forces the live
    passthrough so the mocks are reached instead of the cassette decision
    (#1597 — the only place allowed to bypass is the layer testing itself)."""
    monkeypatch.setenv("LLM_LIVE", "1")


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
    """AC-llm.2.2: litellm_stream yields content deltas, skipping empty ones."""
    out = [
        c async for c in litellm_stream([{"role": "user", "content": "hi"}], provider=_provider(), model_id="glm-5.1")
    ]
    assert "".join(out) == "Hello"


async def test_AC23_2_2_stream_sets_drop_params_and_passes_seed_extra_body(captured):
    """AC-llm.2.2: drop_params is on; seed is native; Z.AI knobs ride extra_body."""
    async for _ in litellm_stream(
        [{"role": "user", "content": "hi"}],
        provider=_provider(),
        model_id="glm-5.1",
        decode=DecodeParams(seed=7, extra_body={"do_sample": False, "thinking": {"type": "disabled"}}),
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
    """AC-llm.2.4: per-scene knobs (reasoning depth, max_tokens, temperature) reach litellm."""
    from src.llm.base import ReasoningEffort

    async for _ in litellm_stream(
        [{"role": "user", "content": "hi"}],
        provider=_provider(),
        model_id="glm-5.1",
        decode=DecodeParams(max_tokens=256, temperature=0.0, reasoning=ReasoningEffort.MEDIUM),
    ):
        pass
    kw = captured["kwargs"]
    assert kw["max_tokens"] == 256
    assert kw["temperature"] == 0.0
    assert kw["reasoning_effort"] == "medium"


def _gemini_provider() -> ProviderRef:
    return ProviderRef(id="env", label="gemini", protocol=ProtocolFamily.GOOGLE_GEMINI, api_key="k")


async def test_gemini_disables_thinking_when_no_reasoning_requested(captured):
    """Gemini 2.5+ thinks by default and those thinking tokens are charged against the
    output budget, truncating a verbose extraction mid-JSON. With no reasoning requested,
    the live call must carry reasoning_effort="disable" — and only for Gemini."""
    async for _ in litellm_stream(
        [{"role": "user", "content": "hi"}], provider=_gemini_provider(), model_id="gemini-3-flash-preview"
    ):
        pass
    assert captured["kwargs"]["reasoning_effort"] == "disable"
    assert captured["kwargs"]["model"] == "gemini/gemini-3-flash-preview"
    assert captured["kwargs"].get("api_base") is None


async def test_non_gemini_no_reasoning_omits_reasoning_effort(captured):
    """The disable is Gemini-only: Z.AI/GLM with no reasoning sends no reasoning_effort."""
    async for _ in litellm_stream([{"role": "user", "content": "hi"}], provider=_provider(), model_id="glm-5.1"):
        pass
    assert "reasoning_effort" not in captured["kwargs"]


async def test_AC23_2_3_provider_error_is_normalised_to_llmerror(monkeypatch):
    """AC-llm.2.3: a transient provider failure becomes a retryable LLMError."""

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
    """AC-llm.2.3: an unknown provider error is wrapped as non-retryable."""

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
    """AC-llm.2.2: a 'provider_id/model' binding selects that provider among several."""
    p_zai = _provider()
    p_or = ProviderRef(id="router", label="or", protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key="k2")
    provider, model = await resolve_provider_and_model(_FakeConfig([p_zai, p_or]), "router/deepseek-chat")
    assert provider is p_or
    assert model == "deepseek-chat"


async def test_AC23_2_2_ambiguous_unqualified_model_with_many_providers_errors():
    """AC-llm.2.2: an unqualified model with >1 provider is rejected, not guessed."""
    p1 = _provider()
    p2 = ProviderRef(id="other", label="o", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k2")
    with pytest.raises(LLMConfigError):
        await resolve_provider_and_model(_FakeConfig([p1, p2]), "glm-5.1")


async def test_AC23_2_2_no_provider_configured_errors():
    """AC-llm.2.2: resolving with zero providers is a config error."""
    with pytest.raises(LLMConfigError):
        await resolve_provider_and_model(_FakeConfig([]), "glm-5.1")


async def test_AC23_2_2_unknown_qualified_provider_raises_not_silently_falls_back():
    """AC-llm.2.2: a provider_id-qualified model whose provider is unknown raises, not silently wrong creds."""
    p1 = _provider()
    p2 = ProviderRef(id="other", label="o", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k2")
    with pytest.raises(LLMConfigError):
        await resolve_provider_and_model(_FakeConfig([p1, p2]), "ghost/model")


async def test_AC23_2_2_single_provider_honours_db_style_qualified_binding():
    """AC-llm.2.2: a DB binding qualified as provider_id/model strips the id even with one provider."""
    p = ProviderRef(id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="k", api_base="https://z")
    provider, model = await resolve_provider_and_model(_FakeConfig([p]), "env/glm-5.1")
    assert provider is p
    assert model == "glm-5.1"


async def test_AC23_2_2_single_provider_keeps_slashed_openrouter_model():
    """AC-llm.2.2: with one provider an OpenRouter vendor/model id is used whole, not split as provider."""
    p = ProviderRef(id="env", label="or", protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key="k")
    provider, model = await resolve_provider_and_model(_FakeConfig([p]), "deepseek/deepseek-chat")
    assert provider is p
    assert model == "deepseek/deepseek-chat"


class _FakeResponse:
    """A litellm-style response exposing model_dump (pydantic-ish)."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return dict(self._payload)


async def test_AC23_5_4_cassette_completion_off_mode_does_a_live_litellm_call(monkeypatch, tmp_path):
    """AC-llm.5.4: cassette_completion in off mode performs the real (mocked) litellm
    call and projects the response dict; no cassette is written."""
    from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore
    from src.llm.extension.client import cassette_completion

    async def fake_acompletion(**kwargs):
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    store = CassetteStore(directory=tmp_path / "c")
    recorder = CassetteRecorder(store, mode=CassetteMode.OFF)
    out = await cassette_completion(
        [{"role": "user", "content": "hi"}],
        role="advisor.chat",
        provider=_provider(),
        model_id="glm-5.1",
        recorder=recorder,
        decode=DecodeParams(temperature=0.0, max_tokens=16),
    )
    assert out == {"choices": [{"message": {"content": "ok"}}]}


async def test_AC23_5_4_cassette_completion_record_then_replay_roundtrips(monkeypatch, tmp_path):
    """AC-llm.5.4 + AC-llm.5.2: record performs the live call and freezes it; a later
    replay serves it back with no live call (the model id may differ — keying is
    model-id-agnostic)."""
    from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore
    from src.llm.extension.client import cassette_completion

    async def fake_acompletion(**kwargs):
        return _FakeResponse({"text": "frozen"})

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    store = CassetteStore(directory=tmp_path / "c")
    messages = [{"role": "user", "content": "balance?"}]

    rec = await cassette_completion(
        messages,
        role="extraction.json",
        provider=_provider(),
        model_id="glm-5.1",
        recorder=CassetteRecorder(store, mode=CassetteMode.RECORD),
        decode=DecodeParams(temperature=0.0),
    )
    assert rec == {"text": "frozen"}

    async def explode(**kwargs):  # pragma: no cover - replay must not call litellm
        raise AssertionError("replay must not call litellm")

    monkeypatch.setattr(client_mod.litellm, "acompletion", explode)
    # A different model id resolves the SAME cassette (model-id-agnostic key).
    play = await cassette_completion(
        messages,
        role="extraction.json",
        provider=_provider(),
        model_id="glm-5.2",
        recorder=CassetteRecorder(store, mode=CassetteMode.REPLAY),
        decode=DecodeParams(temperature=0.0),
    )
    assert play == {"text": "frozen"}


async def test_AC23_5_4_cassette_completion_record_wraps_provider_error(monkeypatch, tmp_path):
    """AC-llm.5.4: a provider failure during a record live call is normalised to LLMError."""
    from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore
    from src.llm.extension.client import cassette_completion

    async def boom(**kwargs):
        raise ValueError("bad request")

    monkeypatch.setattr(client_mod.litellm, "acompletion", boom)
    store = CassetteStore(directory=tmp_path / "c")
    with pytest.raises(LLMError):
        await cassette_completion(
            [{"role": "user", "content": "x"}],
            role="advisor.chat",
            provider=_provider(),
            model_id="m",
            recorder=CassetteRecorder(store, mode=CassetteMode.RECORD),
        )


async def test_AC23_5_4_cassette_completion_all_decode_params_and_dict_response(monkeypatch, tmp_path):
    """AC-llm.5.4: reasoning/seed/extra_body/timeout knobs reach the live call and a
    plain-dict response (no model_dump) is returned as-is."""
    from src.llm.base import ReasoningEffort
    from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore
    from src.llm.extension.client import cassette_completion

    captured_kwargs: dict = {}

    async def fake_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return {"plain": "dict"}

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    store = CassetteStore(directory=tmp_path / "c")
    out = await cassette_completion(
        [{"role": "user", "content": "hi"}],
        role="extraction.vision",
        provider=_provider(),
        model_id="glm-4.6V",
        recorder=CassetteRecorder(store, mode=CassetteMode.RECORD),
        decode=DecodeParams(
            reasoning=ReasoningEffort.MEDIUM,
            seed=11,
            extra_body={"thinking": {"type": "disabled"}},
        ),
        timeout=5.0,
    )
    assert out == {"plain": "dict"}
    assert captured_kwargs["reasoning_effort"] == "medium"
    assert captured_kwargs["seed"] == 11
    assert captured_kwargs["timeout"] == 5.0


async def test_AC23_5_4_cassette_completion_stringifies_opaque_response(monkeypatch, tmp_path):
    """AC-llm.5.4: an opaque response (no model_dump, not a dict) is projected to a
    text payload so any provider shape is freezable."""
    from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore
    from src.llm.extension.client import cassette_completion

    async def fake_acompletion(**kwargs):
        return 12345  # opaque, neither pydantic nor dict

    monkeypatch.setattr(client_mod.litellm, "acompletion", fake_acompletion)
    store = CassetteStore(directory=tmp_path / "c")
    out = await cassette_completion(
        [{"role": "user", "content": "hi"}],
        role="advisor.chat",
        provider=_provider(),
        model_id="m",
        recorder=CassetteRecorder(store, mode=CassetteMode.RECORD),
    )
    assert out == {"text": "12345"}


async def test_AC23_5_4_cassette_completion_passes_through_llmerror(monkeypatch, tmp_path):
    """AC-llm.5.4: an LLMError raised by the transport is re-raised unchanged (not
    re-wrapped), preserving its retryable verdict."""
    from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore
    from src.llm.extension.client import cassette_completion

    async def raise_llmerror(**kwargs):
        raise LLMError("already normalised", retryable=True)

    monkeypatch.setattr(client_mod.litellm, "acompletion", raise_llmerror)
    store = CassetteStore(directory=tmp_path / "c")
    with pytest.raises(LLMError) as ei:
        await cassette_completion(
            [{"role": "user", "content": "x"}],
            role="advisor.chat",
            provider=_provider(),
            model_id="m",
            recorder=CassetteRecorder(store, mode=CassetteMode.RECORD),
        )
    assert ei.value.retryable is True


def test_AC23_9_1_litellm_aiohttp_transport_disabled_prevents_session_leak():
    """AC-llm.9.1: importing the litellm client disables litellm's aiohttp transport.

    litellm's aiohttp transport lazily creates an aiohttp ClientSession per
    request handler and never closes it, leaking an "Unclosed client session"
    on every acompletion (#1442). Routing through the httpx transport litellm
    manages itself avoids the leak. ``src.llm.extension.client`` is imported at module top,
    so the hardening has already run.

    Asserts only the public, documented ``litellm.disable_aiohttp_transport`` flag
    (litellm's opt-out contract) — not any private transport-selection internal,
    which is brittle across litellm versions (CR on #1462).
    """
    import litellm

    assert client_mod.litellm.disable_aiohttp_transport is True
    assert litellm.disable_aiohttp_transport is True
