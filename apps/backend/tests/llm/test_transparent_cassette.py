"""#1596: the cassette layer decides per-request; downstream never knows real-vs-frozen.

Decision table under test (all inside the llm layer):

    LLM_LIVE=1 (workflow/deployment-owned)  -> live passthrough, store untouched
    layer not engaged (prod/app runtime)    -> live passthrough
    engaged (test harness bootstraps once):
        HIT                                  -> serve frozen (never resolves credentials)
        HIT + REFRESH (local only) + key     -> real call, re-record
        MISS + CI                            -> hard CassetteMiss (even with a key)
        MISS + key (local)                   -> real call + auto-record the new cassette
        MISS + no key (local)                -> hard CassetteMiss ("needs recording")
    RECORD/REFRESH are refused in CI; LIVE is explicit workflow config (allowed).
"""

from __future__ import annotations

import pytest

from src.llm.base.types import ProtocolFamily, ProviderRef
from src.llm.extension.cassette import CassetteMiss, CassetteStore, fingerprint
from src.llm.extension.client import _stream_decode_params, litellm_stream

MESSAGES = [{"role": "user", "content": "transparent-cassette probe"}]
_DECODE = _stream_decode_params(max_tokens=64, temperature=None, reasoning=None, seed=None, extra_body=None)
KEY = fingerprint(role="text", messages=MESSAGES, decode_params=_DECODE)


def _provider() -> ProviderRef:
    return ProviderRef(id="p", label="p", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="real-key", api_base=None)


@pytest.fixture
def store(tmp_path):
    return CassetteStore(directory=tmp_path)


@pytest.fixture
def frozen(store):
    """A pre-recorded cassette for MESSAGES."""
    from src.llm.extension.cassette import Cassette, CassetteTag
    from src.llm.extension.client import _canonical_request

    request = _canonical_request(role="text", messages=MESSAGES, decode_params=_DECODE)
    store.put(
        Cassette(key=KEY, role="text", tag=CassetteTag.FLOW_ONLY, request=request, response={"stream_text": "FROZEN"})
    )
    return store


@pytest.fixture
def no_network(monkeypatch):
    """The live transport must not be touched; record calls if it is."""
    calls: list[dict] = []

    async def fake_live(kwargs):
        calls.append(kwargs)
        yield "LIVE-RESPONSE"

    monkeypatch.setattr("src.llm.extension.client._litellm_stream_live", fake_live)
    return calls


async def _run(*, store, provider=None, provider_resolver=None, **cassette_kwargs):
    chunks = []
    async for c in litellm_stream(
        MESSAGES,
        provider=provider,
        provider_resolver=provider_resolver,
        model_id="glm-test",
        max_tokens=64,
        cassette_store=store,
        **cassette_kwargs,
    ):
        chunks.append(c)
    return "".join(chunks)


def _engage(monkeypatch, *, ci=False, refresh=False, live=False):
    monkeypatch.setenv("LLM_CASSETTE_ENGAGE", "1")
    monkeypatch.delenv("LLM_CASSETTE_MODE", raising=False)
    for name, on in (("CI", ci), ("LLM_CASSETTE_REFRESH", refresh), ("LLM_LIVE", live)):
        monkeypatch.setenv(name, "1") if on else monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_hit_serves_frozen_without_credentials(frozen, no_network, monkeypatch):
    """AC-llm.10.1: HIT: the frozen response is served with NO provider and NO key resolution."""
    _engage(monkeypatch)
    out = await _run(store=frozen, provider=None, provider_resolver=None)
    assert out == "FROZEN"
    assert no_network == []  # network never touched


@pytest.mark.asyncio
async def test_miss_without_key_is_hard_red(store, no_network, monkeypatch):
    """AC-llm.10.2: MISS + no key (local): hard CassetteMiss — never a silent skip or fallback."""
    _engage(monkeypatch)
    with pytest.raises(CassetteMiss):
        await _run(store=store, provider=None, provider_resolver=None)
    assert no_network == []


@pytest.mark.asyncio
async def test_miss_in_ci_is_hard_red_even_with_key(store, no_network, monkeypatch):
    """AC-llm.10.2: MISS + CI: hard failure even with a usable key — CI never calls the network."""
    _engage(monkeypatch, ci=True)
    with pytest.raises(CassetteMiss):
        await _run(store=store, provider=_provider())
    assert no_network == []


@pytest.mark.asyncio
async def test_miss_with_key_records_locally(store, no_network, monkeypatch):
    """AC-llm.10.3: MISS + key (local): real call + the new cassette is auto-recorded."""
    _engage(monkeypatch)
    out = await _run(store=store, provider=_provider())
    assert out == "LIVE-RESPONSE"
    assert len(no_network) == 1
    assert store.get(KEY) is not None  # recorded


@pytest.mark.asyncio
async def test_hit_never_rerecords_without_refresh(frozen, no_network, monkeypatch):
    """AC-llm.10.3: a HIT never re-records without the refresh knob."""
    _engage(monkeypatch)
    out = await _run(store=frozen, provider=_provider())
    assert out == "FROZEN" and no_network == []


@pytest.mark.asyncio
async def test_refresh_rerecords_a_hit_locally(frozen, no_network, monkeypatch):
    """AC-llm.10.4: REFRESH (local, layer-owned): a HIT is re-recorded from the real call."""
    _engage(monkeypatch, refresh=True)
    out = await _run(store=frozen, provider=_provider())
    assert out == "LIVE-RESPONSE"
    assert len(no_network) == 1
    assert str(frozen.get(KEY).response.get("stream_text")) == "LIVE-RESPONSE"


@pytest.mark.asyncio
async def test_refresh_is_refused_in_ci(frozen, no_network, monkeypatch):
    """AC-llm.10.4: REFRESH in CI: refused — cassettes are never written in CI; the HIT serves."""
    _engage(monkeypatch, ci=True, refresh=True)
    out = await _run(store=frozen, provider=_provider())
    assert out == "FROZEN" and no_network == []


@pytest.mark.asyncio
async def test_live_bypasses_the_store_entirely(frozen, no_network, monkeypatch):
    """AC-llm.10.5: LLM_LIVE (explicit workflow/deployment config): passthrough; store untouched."""
    _engage(monkeypatch, live=True)
    out = await _run(store=frozen, provider=_provider())
    assert out == "LIVE-RESPONSE"
    assert str(frozen.get(KEY).response.get("stream_text")) == "FROZEN"  # not re-recorded


@pytest.mark.asyncio
async def test_not_engaged_is_live_passthrough(frozen, no_network, monkeypatch):
    """AC-llm.10.5: Prod/app runtime (layer not engaged): exact live passthrough, store untouched."""
    for name in ("LLM_CASSETTE_ENGAGE", "LLM_CASSETTE_MODE", "CI", "LLM_LIVE", "LLM_CASSETTE_REFRESH"):
        monkeypatch.delenv(name, raising=False)
    out = await _run(store=frozen, provider=_provider())
    assert out == "LIVE-RESPONSE"


@pytest.mark.asyncio
async def test_lazy_provider_resolution_only_on_network(frozen, tmp_path, no_network, monkeypatch):
    """AC-llm.10.1: The layer resolves credentials ONLY when it actually needs the network:
    a HIT never invokes the resolver; a local MISS with a resolver does."""
    _engage(monkeypatch)
    resolved: list[str] = []

    async def resolver() -> ProviderRef:
        resolved.append("x")
        return _provider()

    assert await _run(store=frozen, provider_resolver=resolver) == "FROZEN"
    assert resolved == []  # HIT: never resolved

    empty = CassetteStore(directory=tmp_path / "empty")
    out = await _run(store=empty, provider_resolver=resolver)
    assert out == "LIVE-RESPONSE" and resolved == ["x"]  # MISS: resolved once


@pytest.mark.asyncio
async def test_served_keys_are_tracked_for_orphan_detection(frozen, no_network, monkeypatch):
    """AC-llm.10.6: Orphan detection substrate: the store tracks which cassettes were served."""
    _engage(monkeypatch)
    await _run(store=frozen)
    assert KEY in frozen.served_keys()


@pytest.mark.asyncio
async def test_auto_record_enforces_the_correctness_red_line(store, no_network, monkeypatch):
    """AC-llm.10.8: transparent auto-record enforces the correctness red line: a
    correctness-tagged request is refused without a ground-truth validator, and a
    response failing validation is NEVER frozen."""
    from src.llm.extension.cassette import CassetteTag, CassetteValidationError

    _engage(monkeypatch)
    with pytest.raises(CassetteValidationError):
        await _run(store=store, provider=_provider(), cassette_tag=CassetteTag.CORRECTNESS)
    assert store.get(KEY) is None  # nothing frozen without a validator

    with pytest.raises(CassetteValidationError):
        await _run(
            store=store,
            provider=_provider(),
            cassette_tag=CassetteTag.CORRECTNESS,
            cassette_validator=lambda response: False,
        )
    assert store.get(KEY) is None  # a failing response is never frozen

    out = await _run(
        store=store,
        provider=_provider(),
        cassette_tag=CassetteTag.CORRECTNESS,
        cassette_validator=lambda response: response["stream_text"] == "LIVE-RESPONSE",
    )
    assert out == "LIVE-RESPONSE"
    assert store.get(KEY) is not None  # a validated response freezes normally
