from __future__ import annotations; import pytest; from src.llm.base.types import DecodeParams, ProtocolFamily, ProviderRef; from src.llm.extension.cassette import CassetteMiss, CassetteStore, CassetteTag, fingerprint; from src.llm.extension.client import CassetteOptions, litellm_stream; MESSAGES = [{'role': 'user', 'content': 'transparent-cassette probe'}]; _DECODE = DecodeParams(max_tokens=64).as_request(); KEY = fingerprint(role='text', messages=MESSAGES, decode_params=_DECODE); _provider = lambda: ProviderRef(id='p', label='p', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='real-key', api_base=None)
@pytest.fixture
def store(tmp_path): return CassetteStore(directory=tmp_path)
@pytest.fixture
def frozen(store): from src.llm.extension.cassette import Cassette, CassetteTag; from src.llm.extension.client import _canonical_request; request = _canonical_request(role='text', messages=MESSAGES, decode_params=_DECODE); store.put(Cassette(key=KEY, role='text', tag=CassetteTag.FLOW_ONLY, request=request, response={'stream_text': 'FROZEN'})); return store
@pytest.fixture
def no_network(monkeypatch):
    calls: list[dict] = []
    async def fake_live(kwargs): calls.append(kwargs); yield 'LIVE-RESPONSE'
    monkeypatch.setattr('src.llm.extension.client._litellm_stream_live', fake_live); return calls
async def _run(*, store, provider=None, provider_resolver=None, **cassette_kwargs):
    chunks = []; options = CassetteOptions(store=store, mode=cassette_kwargs.get('cassette_mode'), tag=cassette_kwargs.get('cassette_tag', CassetteTag.FLOW_ONLY), validator=cassette_kwargs.get('cassette_validator'))
    async for c in litellm_stream(MESSAGES, provider=provider, provider_resolver=provider_resolver, model_id='glm-test', decode=DecodeParams(max_tokens=64), cassette=options): chunks.append(c)
    return ''.join(chunks)
def _engage(monkeypatch, *, ci=False, refresh=False, live=False): monkeypatch.setenv('LLM_CASSETTE_ENGAGE', '1'); monkeypatch.delenv('LLM_CASSETTE_MODE', raising=False); [monkeypatch.setenv(name, '1') if on else monkeypatch.delenv(name, raising=False) for name, on in (('CI', ci), ('LLM_CASSETTE_REFRESH', refresh), ('LLM_LIVE', live))]
async def test_hit_serves_frozen_without_credentials(frozen, no_network, monkeypatch): 'AC-llm.10.1'; _engage(monkeypatch); out = await _run(store=frozen, provider=None, provider_resolver=None); assert out == 'FROZEN'; assert no_network == []
async def test_miss_without_key_is_hard_red(store, no_network, monkeypatch):
    'AC-llm.10.2'; _engage(monkeypatch)
    with pytest.raises(CassetteMiss): await _run(store=store, provider=None, provider_resolver=None)
    assert no_network == []
async def test_miss_in_ci_is_hard_red_even_with_key(store, no_network, monkeypatch):
    'AC-llm.10.2'; _engage(monkeypatch, ci=True)
    with pytest.raises(CassetteMiss): await _run(store=store, provider=_provider())
    assert no_network == []
async def test_miss_with_key_records_locally(store, no_network, monkeypatch): 'AC-llm.10.3'; _engage(monkeypatch); out = await _run(store=store, provider=_provider()); assert out == 'LIVE-RESPONSE'; assert len(no_network) == 1; assert store.get(KEY) is not None
async def test_hit_never_rerecords_without_refresh(frozen, no_network, monkeypatch): 'AC-llm.10.3'; _engage(monkeypatch); out = await _run(store=frozen, provider=_provider()); assert out == 'FROZEN' and no_network == []
async def test_refresh_rerecords_a_hit_locally(frozen, no_network, monkeypatch): 'AC-llm.10.4'; _engage(monkeypatch, refresh=True); out = await _run(store=frozen, provider=_provider()); assert out == 'LIVE-RESPONSE'; assert len(no_network) == 1; assert str(frozen.get(KEY).response.get('stream_text')) == 'LIVE-RESPONSE'
async def test_refresh_is_refused_in_ci(frozen, no_network, monkeypatch): 'AC-llm.10.4'; _engage(monkeypatch, ci=True, refresh=True); out = await _run(store=frozen, provider=_provider()); assert out == 'FROZEN' and no_network == []
async def test_live_bypasses_the_store_entirely(frozen, no_network, monkeypatch): 'AC-llm.10.5'; _engage(monkeypatch, live=True); out = await _run(store=frozen, provider=_provider()); assert out == 'LIVE-RESPONSE'; assert str(frozen.get(KEY).response.get('stream_text')) == 'FROZEN'
async def test_not_engaged_is_live_passthrough(frozen, no_network, monkeypatch): 'AC-llm.10.5'; [monkeypatch.delenv(name, raising=False) for name in ('LLM_CASSETTE_ENGAGE', 'LLM_CASSETTE_MODE', 'CI', 'LLM_LIVE', 'LLM_CASSETTE_REFRESH')]; out = await _run(store=frozen, provider=_provider()); assert out == 'LIVE-RESPONSE'
async def test_lazy_provider_resolution_only_on_network(frozen, tmp_path, no_network, monkeypatch):
    'AC-llm.10.1'; _engage(monkeypatch); resolved: list[str] = []
    async def resolver() -> ProviderRef: resolved.append('x'); return _provider()
    assert await _run(store=frozen, provider_resolver=resolver) == 'FROZEN'; assert resolved == []; empty = CassetteStore(directory=tmp_path / 'empty'); out = await _run(store=empty, provider_resolver=resolver); assert out == 'LIVE-RESPONSE' and resolved == ['x']
async def test_served_keys_are_tracked_for_orphan_detection(frozen, no_network, monkeypatch): 'AC-llm.10.6'; _engage(monkeypatch); await _run(store=frozen); assert KEY in frozen.served_keys()
async def test_auto_record_enforces_the_correctness_red_line(store, no_network, monkeypatch):
    'AC-llm.10.8'; from src.llm.extension.cassette import CassetteTag, CassetteValidationError; _engage(monkeypatch)
    with pytest.raises(CassetteValidationError): await _run(store=store, provider=_provider(), cassette_tag=CassetteTag.CORRECTNESS)
    assert store.get(KEY) is None
    with pytest.raises(CassetteValidationError): await _run(store=store, provider=_provider(), cassette_tag=CassetteTag.CORRECTNESS, cassette_validator=lambda response: False)
    assert store.get(KEY) is None; out = await _run(store=store, provider=_provider(), cassette_tag=CassetteTag.CORRECTNESS, cassette_validator=lambda response: response['stream_text'] == 'LIVE-RESPONSE'); assert out == 'LIVE-RESPONSE'; assert store.get(KEY) is not None
