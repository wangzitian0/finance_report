from __future__ import annotations

import pytest

from src.llm.base.types import DecodeParams, ProtocolFamily, ProviderRef
from src.llm.extension.cassette import Cassette, CassetteMiss, CassetteStore, CassetteTag, CassetteValidationError, fingerprint
from src.llm.extension.client import CassetteOptions, _canonical_request, litellm_stream

MESSAGES = [{"role": "system", "content": "x"}][:0] + [{"role": "user", "content": "transparent-cassette probe"}]
_DECODE = DecodeParams(max_tokens=64).as_request()
KEY = fingerprint(role="text", messages=MESSAGES, decode_params=_DECODE)
_provider = lambda: ProviderRef(id="p", label="p", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="real-key", api_base=None)


@pytest.fixture
def no_network(monkeypatch):
    calls: list[dict] = []

    async def fake_live(kwargs):
        calls.append(kwargs)
        yield "LIVE-RESPONSE"

    monkeypatch.setattr("src.llm.extension.client._litellm_stream_live", fake_live)
    return calls


async def _run(*, store, provider=None, provider_resolver=None, tag=CassetteTag.FLOW_ONLY, validator=None):
    return "".join([c async for c in litellm_stream(MESSAGES, provider=provider, provider_resolver=provider_resolver, model_id="glm-test", decode=DecodeParams(max_tokens=64), cassette=CassetteOptions(store=store, tag=tag, validator=validator))])


def _engage(monkeypatch, *, engaged: bool = True, ci: bool = False, refresh: bool = False, live: bool = False) -> None:
    monkeypatch.delenv("LLM_CASSETTE_MODE", raising=False)
    for name, on in (("LLM_CASSETTE_ENGAGE", engaged), ("CI", ci), ("LLM_CASSETTE_REFRESH", refresh), ("LLM_LIVE", live)):
        monkeypatch.setenv(name, "1") if on else monkeypatch.delenv(name, raising=False)


def _frozen_store(tmp_path) -> CassetteStore:
    store = CassetteStore(directory=tmp_path / "frozen")
    store.put(Cassette(key=KEY, role="text", tag=CassetteTag.FLOW_ONLY, request=_canonical_request(role="text", messages=MESSAGES, decode_params=_DECODE), response={"stream_text": "FROZEN"}))
    return store


@pytest.mark.parametrize(
    ("use_frozen", "flags", "with_provider", "expected_out", "expected_calls", "expect_stored"),
    [(True, {}, False, "FROZEN", 0, "FROZEN"), (False, {}, True, "LIVE-RESPONSE", 1, "LIVE-RESPONSE"), (True, {}, True, "FROZEN", 0, "FROZEN"), (True, {"refresh": True}, True, "LIVE-RESPONSE", 1, "LIVE-RESPONSE"), (True, {"ci": True, "refresh": True}, True, "FROZEN", 0, "FROZEN"), (True, {"live": True}, True, "LIVE-RESPONSE", 1, "FROZEN"), (True, {"engaged": False}, True, "LIVE-RESPONSE", 1, "FROZEN")],
)
async def test_transparent_cassette_mode_matrix(tmp_path, no_network, monkeypatch, use_frozen: bool, flags: dict, with_provider: bool, expected_out: str, expected_calls: int, expect_stored: str) -> None:
    target_store = _frozen_store(tmp_path) if use_frozen else CassetteStore(directory=tmp_path / "empty")
    _engage(monkeypatch, **flags)
    out = await _run(store=target_store, provider=_provider() if with_provider else None)
    assert (out, len(no_network), target_store.get(KEY).response.get("stream_text")) == (expected_out, expected_calls, expect_stored)
    if flags == {} and use_frozen:
        assert KEY in target_store.served_keys()


@pytest.mark.parametrize(("ci", "with_provider"), [(False, False), (True, True)])
async def test_miss_without_recording_is_hard_red(tmp_path, no_network, monkeypatch, ci: bool, with_provider: bool) -> None:
    _engage(monkeypatch, ci=ci)
    with pytest.raises(CassetteMiss):
        await _run(store=CassetteStore(directory=tmp_path), provider=_provider() if with_provider else None)
    assert no_network == []


async def test_lazy_provider_resolution_and_correctness_red_line(tmp_path, no_network, monkeypatch) -> None:
    _engage(monkeypatch)
    frozen, empty, resolved = _frozen_store(tmp_path), CassetteStore(directory=tmp_path / "empty"), []

    async def resolver() -> ProviderRef:
        resolved.append("x")
        return _provider()

    assert (await _run(store=frozen, provider_resolver=resolver), resolved) == ("FROZEN", [])
    assert (await _run(store=empty, provider_resolver=resolver), resolved) == ("LIVE-RESPONSE", ["x"])

    c_store = CassetteStore(directory=tmp_path / "corr")
    for validator in (None, lambda _r: False):
        with pytest.raises(CassetteValidationError):
            await _run(store=c_store, provider=_provider(), tag=CassetteTag.CORRECTNESS, validator=validator)
        assert c_store.get(KEY) is None
    assert await _run(store=c_store, provider=_provider(), tag=CassetteTag.CORRECTNESS, validator=lambda r: r["stream_text"] == "LIVE-RESPONSE") == "LIVE-RESPONSE" and c_store.get(KEY) is not None
