'AC-llm.2.2 AC-llm.2.3 EPIC-023'; from __future__ import annotations; import pytest; import src.llm.extension.client as client_mod; from src.llm.base import DecodeParams, LLMConfigError, LLMError, ProtocolFamily, ProviderRef, ReasoningEffort; from src.llm.extension.client import litellm_stream, resolve_provider_and_model
@pytest.fixture(autouse=True)
def _live_transport(monkeypatch): monkeypatch.setenv('LLM_LIVE', '1')
class _Delta:
    def __init__(self, content: str | None) -> None: self.content = content
class _Choice:
    def __init__(self, content: str | None) -> None: self.delta = _Delta(content); self.message = _Delta(content); self.finish_reason = None
class _Chunk:
    def __init__(self, content: str | None) -> None: self.choices = [_Choice(content)]
_provider = lambda: ProviderRef(id='env', label='zai', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k', api_base='https://api.z.ai')
@pytest.fixture
def captured(monkeypatch):
    box: dict = {}
    async def fake_acompletion(**kwargs):
        box['kwargs'] = kwargs
        async def gen():
            for piece in ('Hel', '', 'lo'): yield _Chunk(piece)
        return gen()
    monkeypatch.setattr(client_mod.litellm, 'acompletion', fake_acompletion); return box
async def test_AC23_2_2_stream_yields_only_nonempty_deltas(captured): 'AC-llm.2.2'; out = [c async for c in litellm_stream([{'role': 'user', 'content': 'hi'}], provider=_provider(), model_id='glm-5.1')]; assert ''.join(out) == 'Hello'
async def test_AC23_2_2_stream_sets_drop_params_and_passes_seed_extra_body(captured):
    'AC-llm.2.2'
    async for _ in litellm_stream([{'role': 'user', 'content': 'hi'}], provider=_provider(), model_id='glm-5.1', decode=DecodeParams(seed=7, extra_body={'do_sample': False, 'thinking': {'type': 'disabled'}})): pass
    kw = captured['kwargs']; assert kw['drop_params'] is True; assert kw['stream'] is True; assert kw['seed'] == 7; assert kw['extra_body'] == {'do_sample': False, 'thinking': {'type': 'disabled'}}; assert kw['model'] == 'openai/glm-5.1'; assert kw['api_base'] == 'https://api.z.ai'
async def test_AC23_2_4_reasoning_max_tokens_temperature_passthrough(captured):
    'AC-llm.2.4'; from src.llm.base import ReasoningEffort
    async for _ in litellm_stream([{'role': 'user', 'content': 'hi'}], provider=_provider(), model_id='glm-5.1', decode=DecodeParams(max_tokens=256, temperature=0.0, reasoning=ReasoningEffort.MEDIUM)): pass
    kw = captured['kwargs']; assert kw['max_tokens'] == 256; assert kw['temperature'] == 0.0; assert kw['reasoning_effort'] == 'medium'
_gemini_provider = lambda: ProviderRef(id='env', label='gemini', protocol=ProtocolFamily.GOOGLE_GEMINI, api_key='k')
@pytest.mark.no_db
@pytest.mark.parametrize('model_id', ['glm-5.3', 'glm-5.3-flash', 'openai/GLM-5.3-Flash', 'glm-5.3-flashx', 'openai/GLM-5.3-FlashX'])
@pytest.mark.parametrize(('reasoning', 'expected'), [(None, 'low'), (ReasoningEffort.NONE, 'low'), (ReasoningEffort.LOW, 'low'), (ReasoningEffort.MEDIUM, 'high'), (ReasoningEffort.HIGH, 'high')])
async def test_glm53_stream_uses_supported_reasoning_parameters(captured, model_id, reasoning, expected): 'AC-llm.2.7'; extra_body = {'do_sample': False, 'thinking': {'type': 'disabled', 'clear_thinking': False}}; decode = DecodeParams(reasoning=reasoning, extra_body=extra_body, max_tokens=8192); result = [chunk async for chunk in litellm_stream([{'role': 'user', 'content': 'Return JSON.'}], provider=_provider(), model_id=model_id, decode=decode)]; wire = captured['kwargs']; assert wire['extra_body']['thinking'] == {'type': 'enabled', 'clear_thinking': False}; assert wire['reasoning_effort'] == expected; from litellm.utils import get_optional_params; forwarded = get_optional_params(model=model_id.removeprefix('openai/'), custom_llm_provider='openai', reasoning_effort=wire['reasoning_effort'], drop_params=wire['drop_params'], allowed_openai_params=wire.get('allowed_openai_params')); assert forwarded['reasoning_effort'] == expected; assert wire['extra_body']['do_sample'] is False; assert wire['max_tokens'] == 8192; assert ''.join(result) == 'Hello'; assert decode.extra_body['thinking']['type'] == 'disabled'; assert extra_body['thinking']['type'] == 'disabled'
@pytest.mark.no_db
async def test_glm53_without_decode_options_uses_bounded_reasoning(captured):
    'AC-llm.2.7'
    async for _ in litellm_stream([{'role': 'user', 'content': 'Hello'}], provider=_provider(), model_id='glm-5.3'): pass
    assert captured['kwargs']['extra_body']['thinking'] == {'type': 'enabled'}; assert captured['kwargs']['reasoning_effort'] == 'low'
async def test_gemini_disables_thinking_when_no_reasoning_requested(captured):
    async for _ in litellm_stream([{'role': 'user', 'content': 'hi'}], provider=_gemini_provider(), model_id='gemini-3-flash-preview'): pass
    assert captured['kwargs']['reasoning_effort'] == 'disable'; assert captured['kwargs']['model'] == 'gemini/gemini-3-flash-preview'; assert captured['kwargs'].get('api_base') is None
async def test_non_gemini_no_reasoning_omits_reasoning_effort(captured):
    async for _ in litellm_stream([{'role': 'user', 'content': 'hi'}], provider=_provider(), model_id='glm-5.1'): pass
    assert 'reasoning_effort' not in captured['kwargs']
async def test_AC23_2_3_provider_error_is_normalised_to_llmerror(monkeypatch):
    'AC-llm.2.3'
    class RateLimitError(Exception): pass
    async def boom(**kwargs): raise RateLimitError('429 slow down')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', boom)
    with pytest.raises(LLMError) as ei:
        async for _ in litellm_stream([{'role': 'user', 'content': 'x'}], provider=_provider(), model_id='m'): pass
    assert ei.value.retryable is True
async def test_AC23_2_3_non_retryable_error_classified(monkeypatch):
    'AC-llm.2.3'
    async def boom(**kwargs): raise ValueError('bad request')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', boom)
    with pytest.raises(LLMError) as ei:
        async for _ in litellm_stream([{'role': 'user', 'content': 'x'}], provider=_provider(), model_id='m'): pass
    assert ei.value.retryable is False
class _FakeConfig:
    def __init__(self, providers: list[ProviderRef]) -> None: self._providers = providers
    async def list_providers(self): return list(self._providers)
    async def get_provider(self, provider_id): return next((p for p in self._providers if p.id == provider_id), None)
async def test_AC23_2_2_resolves_provider_from_qualified_model():
    'AC-llm.2.2'; p_zai = _provider(); p_or = ProviderRef(id='router', label='or', protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key='k2'); provider, model = await resolve_provider_and_model(_FakeConfig([p_zai, p_or]), 'router/deepseek-chat'); assert provider is p_or; assert model == 'deepseek-chat'; 'AC-llm.2.2'; 'AC-llm.2.2'; _m1_p1 = _provider(); _m1_p2 = ProviderRef(id='other', label='o', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k2')
    with pytest.raises(LLMConfigError): await resolve_provider_and_model(_FakeConfig([_m1_p1, _m1_p2]), 'glm-5.1')
    'AC-llm.2.2'; 'AC-llm.2.2'
    with pytest.raises(LLMConfigError): await resolve_provider_and_model(_FakeConfig([]), 'glm-5.1')
    'AC-llm.2.2'; 'AC-llm.2.2'; _m3_p1 = _provider(); _m3_p2 = ProviderRef(id='other', label='o', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k2')
    with pytest.raises(LLMConfigError): await resolve_provider_and_model(_FakeConfig([_m3_p1, _m3_p2]), 'ghost/model')
    'AC-llm.2.2'; 'AC-llm.2.2'; _m4_p = ProviderRef(id='env', label='zai', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k', api_base='https://z'); _m4_provider, _m4_model = await resolve_provider_and_model(_FakeConfig([_m4_p]), 'env/glm-5.1'); assert _m4_provider is _m4_p; assert _m4_model == 'glm-5.1'; 'AC-llm.2.2'; 'AC-llm.2.2'; _m5_p = ProviderRef(id='env', label='or', protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key='k'); _m5_provider, _m5_model = await resolve_provider_and_model(_FakeConfig([_m5_p]), 'deepseek/deepseek-chat'); assert _m5_provider is _m5_p; assert _m5_model == 'deepseek/deepseek-chat'
class _FakeResponse:
    def __init__(self, payload: dict) -> None: self._payload = payload
    def model_dump(self) -> dict: return dict(self._payload)
async def test_AC23_5_4_cassette_completion_off_mode_does_a_live_litellm_call(monkeypatch, tmp_path):
    'AC-llm.5.4'; from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore; from src.llm.extension.client import cassette_completion
    async def fake_acompletion(**kwargs): return _FakeResponse({'choices': [{'message': {'content': 'ok'}}]})
    monkeypatch.setattr(client_mod.litellm, 'acompletion', fake_acompletion); store = CassetteStore(directory=tmp_path / 'c'); recorder = CassetteRecorder(store, mode=CassetteMode.OFF); out = await cassette_completion([{'role': 'user', 'content': 'hi'}], role='advisor.chat', provider=_provider(), model_id='glm-5.1', recorder=recorder, decode=DecodeParams(temperature=0.0, max_tokens=16)); assert out == {'choices': [{'message': {'content': 'ok'}}]}
async def test_AC23_5_4_cassette_completion_record_then_replay_roundtrips(monkeypatch, tmp_path):
    'AC-llm.5.4 AC-llm.5.2'; from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore; from src.llm.extension.client import cassette_completion
    async def fake_acompletion(**kwargs): return _FakeResponse({'text': 'frozen'})
    monkeypatch.setattr(client_mod.litellm, 'acompletion', fake_acompletion); store = CassetteStore(directory=tmp_path / 'c'); messages = [{'role': 'user', 'content': 'balance?'}]; rec = await cassette_completion(messages, role='extraction.json', provider=_provider(), model_id='glm-5.1', recorder=CassetteRecorder(store, mode=CassetteMode.RECORD), decode=DecodeParams(temperature=0.0)); assert rec == {'text': 'frozen'}
    async def explode(**kwargs): raise AssertionError('replay must not call litellm')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', explode); play = await cassette_completion(messages, role='extraction.json', provider=_provider(), model_id='glm-5.2', recorder=CassetteRecorder(store, mode=CassetteMode.REPLAY), decode=DecodeParams(temperature=0.0)); assert play == {'text': 'frozen'}
async def test_AC23_5_4_cassette_completion_record_wraps_provider_error(monkeypatch, tmp_path):
    'AC-llm.5.4'; from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore; from src.llm.extension.client import cassette_completion
    async def boom(**kwargs): raise ValueError('bad request')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', boom); store = CassetteStore(directory=tmp_path / 'c')
    with pytest.raises(LLMError): await cassette_completion([{'role': 'user', 'content': 'x'}], role='advisor.chat', provider=_provider(), model_id='m', recorder=CassetteRecorder(store, mode=CassetteMode.RECORD))
async def test_AC23_5_4_cassette_completion_all_decode_params_and_dict_response(monkeypatch, tmp_path):
    'AC-llm.5.4'; from src.llm.base import ReasoningEffort; from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore; from src.llm.extension.client import cassette_completion; captured_kwargs: dict = {}
    async def fake_acompletion(**kwargs): captured_kwargs.update(kwargs); return {'plain': 'dict'}
    monkeypatch.setattr(client_mod.litellm, 'acompletion', fake_acompletion); store = CassetteStore(directory=tmp_path / 'c'); out = await cassette_completion([{'role': 'user', 'content': 'hi'}], role='extraction.vision', provider=_provider(), model_id='test-vision-model', recorder=CassetteRecorder(store, mode=CassetteMode.RECORD), decode=DecodeParams(reasoning=ReasoningEffort.MEDIUM, seed=11, extra_body={'thinking': {'type': 'disabled'}}), timeout=5.0); assert out == {'plain': 'dict'}; assert captured_kwargs['reasoning_effort'] == 'medium'; assert captured_kwargs['seed'] == 11; assert captured_kwargs['timeout'] == 5.0
async def test_AC23_5_4_cassette_completion_stringifies_opaque_response(monkeypatch, tmp_path):
    'AC-llm.5.4'; from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore; from src.llm.extension.client import cassette_completion
    async def fake_acompletion(**kwargs): return 12345
    monkeypatch.setattr(client_mod.litellm, 'acompletion', fake_acompletion); store = CassetteStore(directory=tmp_path / 'c'); out = await cassette_completion([{'role': 'user', 'content': 'hi'}], role='advisor.chat', provider=_provider(), model_id='m', recorder=CassetteRecorder(store, mode=CassetteMode.RECORD)); assert out == {'text': '12345'}
async def test_AC23_5_4_cassette_completion_passes_through_llmerror(monkeypatch, tmp_path):
    'AC-llm.5.4'; from src.llm.extension.cassette import CassetteMode, CassetteRecorder, CassetteStore; from src.llm.extension.client import cassette_completion
    async def raise_llmerror(**kwargs): raise LLMError('already normalised', retryable=True)
    monkeypatch.setattr(client_mod.litellm, 'acompletion', raise_llmerror); store = CassetteStore(directory=tmp_path / 'c')
    with pytest.raises(LLMError) as ei: await cassette_completion([{'role': 'user', 'content': 'x'}], role='advisor.chat', provider=_provider(), model_id='m', recorder=CassetteRecorder(store, mode=CassetteMode.RECORD))
    assert ei.value.retryable is True
def test_AC23_9_1_litellm_aiohttp_transport_disabled_prevents_session_leak(): 'AC-llm.9.1'; import litellm; assert client_mod.litellm.disable_aiohttp_transport is True; assert litellm.disable_aiohttp_transport is True
class _ProviderError(Exception):
    def __init__(self, message: str, status_code=None): super().__init__(message); self.status_code = status_code
class RateLimitError(_ProviderError): pass
def test_AC_llm_provider_error_code_1_text_names_status_and_code_and_nothing_else():
    'AC-llm.provider-error-code.1'; secret = 'key sk-SECRET-123 at https://open.bigmodel.cn/api/paas/v4/chat Authorization: Bearer abc'; texts = {'python dict repr': f"Error code: 429 - {{'error': {{'code': '1113', 'message': 'Insufficient balance. {secret}'}}}}", 'json': f'{{"error":{{"code":"1113","message":"Insufficient balance. {secret}"}}}}', 'unquoted number': f"Error code: 429 - {{'error': {{'code': 1113, 'message': '{secret}'}}}}"}
    for (label, text) in texts.items():
        err = client_mod._wrap(RateLimitError(text, status_code=429)); assert str(err) == 'LLM provider call failed (RateLimitError, http 429, provider code 1113)', label; assert err.retryable is True
        for leaked in ('sk-SECRET', 'Bearer', 'https://', 'Insufficient'): assert leaked not in str(err), (label, leaked)
    'AC-llm.provider-error-code.1'; 'AC-llm.provider-error-code.1'; assert str(client_mod._wrap(ValueError('bad request'))) == 'LLM provider call failed (ValueError)'
    for _m6_status in ('429', True, 99, 600): _m6_err = client_mod._wrap(_ProviderError('x', status_code=_m6_status)); assert str(_m6_err) == 'LLM provider call failed (_ProviderError)'
    _m6_err = client_mod._wrap(_ProviderError('{"error":{"code":"rate_limited"}}', status_code=429)); assert str(_m6_err) == 'LLM provider call failed (_ProviderError, http 429)'
@pytest.fixture
def provider_429():
    import json; import threading; from http.server import BaseHTTPRequestHandler, HTTPServer; state: dict = {'body': {}}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self): self.rfile.read(int(self.headers.get('content-length', 0))); raw = json.dumps(state['body']).encode(); self.send_response(429); self.send_header('content-type', 'application/json'); self.send_header('content-length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def log_message(self, *args): pass
    server = HTTPServer(('127.0.0.1', 0), Handler); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start(); provider = ProviderRef(id='env', label='zai', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k', api_base=f'http://127.0.0.1:{server.server_port}/v1'); yield (state, provider); server.shutdown(); server.server_close()
async def _text_of_failed_call(provider: ProviderRef) -> tuple[str, bool]:
    with pytest.raises(LLMError) as ei:
        async for _ in litellm_stream([{'role': 'user', 'content': 'x'}], provider=provider, model_id='glm-5.3-flashx'): pass
    return (str(ei.value), ei.value.retryable)
@pytest.mark.parametrize(('body', 'expected'), [({'error': {'code': '1302', 'message': 'Rate limit reached for requests'}}, 'provider code 1302'), ({'error': {'code': 1113, 'message': 'Insufficient balance'}}, 'provider code 1113'), ({'code': 1305, 'msg': 'too many requests', 'success': False}, 'provider code 1305'), ({'error': {'code': 'rate_limited', 'message': 'slow down'}}, None), ({'error': {'message': 'slow down'}}, None)])
async def test_AC_llm_provider_error_code_1_real_429_body_gives_the_code_through_litellm(provider_429, body, expected): 'AC-llm.provider-error-code.1'; state, provider = provider_429; state['body'] = body; text, retryable = await _text_of_failed_call(provider); want = 'LLM provider call failed (RateLimitError, http 429' + (f', {expected}' if expected else '') + ')'; assert text == want; assert retryable is True
async def test_AC_llm_provider_error_code_1_real_429_message_text_never_reaches_the_error(provider_429): 'AC-llm.provider-error-code.1'; state, provider = provider_429; state['body'] = {'error': {'code': '1113', 'message': 'key sk-SECRET-123 at https://x.example/v1 Bearer abc'}}; text, _ = await _text_of_failed_call(provider); assert text == 'LLM provider call failed (RateLimitError, http 429, provider code 1113)'; assert all((leaked not in text for leaked in ('sk-SECRET', 'Bearer', 'https://')))
@pytest.mark.parametrize(('model_id', 'adapted'), [('glm-5.3', True), ('glm-5.3-flash', True), ('openai/GLM-5.3-FlashX', True), ('glm-5.3-turbo', True), ('glm-5.2', False), ('glm-5.3-flash-extra', False), ('gpt-4o', False)])
def test_glm53_adapter_applies_by_model_family_not_by_id_list(model_id, adapted): 'AC-llm.2.7'; decode = DecodeParams(reasoning=ReasoningEffort.NONE, extra_body={'thinking': {'type': 'disabled'}}); kwargs = client_mod._base_kwargs(provider=_provider(), model_id=model_id, messages=[{'role': 'user', 'content': 'x'}], decode=decode); assert (kwargs['extra_body']['thinking']['type'] == 'enabled') is adapted; assert ('allowed_openai_params' in kwargs) is adapted
