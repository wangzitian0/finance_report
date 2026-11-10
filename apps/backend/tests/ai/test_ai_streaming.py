'EPIC-023'; from __future__ import annotations; import pytest; import src.llm.extension.client as client_mod; import src.llm.extension.streaming as streaming; from src.config import settings; from src.llm import AIStreamError, accumulate_stream, stream_ai_chat, stream_ai_json; from src.llm.base import LLMError, ProtocolFamily, ProviderRef; pytestmark = pytest.mark.no_db
class _Delta:
    def __init__(self, c): self.content = c
class _Choice:
    def __init__(self, c): self.delta = _Delta(c)
class _Chunk:
    def __init__(self, c): self.choices = [_Choice(c)]
@pytest.fixture(autouse=True)
def _force_live_transport(monkeypatch): monkeypatch.setenv('LLM_LIVE', '1')
@pytest.fixture
def litellm_stub(monkeypatch):
    box: dict = {}
    async def fake_acompletion(**kwargs):
        box['kwargs'] = kwargs
        async def gen():
            for piece in ('{"ok"', ': true}'): yield _Chunk(piece)
        return gen()
    monkeypatch.setattr(client_mod.litellm, 'acompletion', fake_acompletion); return box
def _explicit_provider(monkeypatch): monkeypatch.setattr(settings, 'ai_provider', 'zai', raising=False); monkeypatch.setattr(settings, 'ai_base_url', 'https://api.z.ai', raising=False)
async def test_stream_ai_json_uses_explicit_credentials(litellm_stub, monkeypatch): _explicit_provider(monkeypatch); text = await accumulate_stream(stream_ai_json([{'role': 'user', 'content': 'x'}], 'test-vision-model', api_key='sk-explicit')); assert text == '{"ok": true}'; kw = litellm_stub['kwargs']; assert kw['model'] == 'openai/test-vision-model'; assert kw['api_base'] == 'https://api.z.ai'; assert kw['drop_params'] is True
async def test_stream_ai_json_forwards_zai_knobs_and_seed(litellm_stub, monkeypatch): 'AC-extraction.116.1'; _explicit_provider(monkeypatch); await accumulate_stream(stream_ai_json([{'role': 'user', 'content': 'x'}], 'test-vision-model', api_key='k', do_sample=False, thinking={'type': 'disabled'}, seed=9, temperature=0.0)); kw = litellm_stub['kwargs']; assert kw['extra_body'] == {'do_sample': False, 'thinking': {'type': 'disabled'}}; assert kw['seed'] == 9; assert kw['temperature'] == 0.0
async def test_stream_ai_json_drops_glm_knobs_for_gemini(litellm_stub, monkeypatch): monkeypatch.setattr(settings, 'ai_provider', 'gemini', raising=False); await accumulate_stream(stream_ai_json([{'role': 'user', 'content': 'x'}], 'gemini-3-flash-preview', api_key='k', do_sample=False, thinking={'type': 'disabled'}, temperature=0.0)); kw = litellm_stub['kwargs']; assert 'extra_body' not in kw; assert kw.get('reasoning_effort') == 'disable'; assert kw['model'] == 'gemini/gemini-3-flash-preview'
async def test_stream_resolves_default_provider_from_config(litellm_stub, monkeypatch):
    class _Cfg:
        async def list_providers(self): return [ProviderRef(id='env', label='zai', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='cfg', api_base='https://z')]
    monkeypatch.setattr(streaming, 'get_config_source', lambda *_a, **_k: _Cfg()); text = await accumulate_stream(stream_ai_chat([{'role': 'user', 'content': 'hi'}], 'glm-5.1')); assert text == '{"ok": true}'; assert litellm_stub['kwargs']['model'] == 'openai/glm-5.1'
async def test_stream_raises_when_no_provider_configured(monkeypatch):
    class _Empty:
        async def list_providers(self): return []
    monkeypatch.setattr(streaming, 'get_config_source', lambda *_a, **_k: _Empty())
    with pytest.raises(AIStreamError): await accumulate_stream(stream_ai_json([{'role': 'user', 'content': 'x'}], 'glm-5.1'))
async def test_stream_fails_closed_with_multiple_providers(monkeypatch):
    class _Multi:
        async def list_providers(self): return [ProviderRef(id='a', label='a', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k1'), ProviderRef(id='b', label='b', protocol=ProtocolFamily.OPENROUTER_COMPATIBLE, api_key='k2')]
    monkeypatch.setattr(streaming, 'get_config_source', lambda *_a, **_k: _Multi())
    with pytest.raises(AIStreamError): await accumulate_stream(stream_ai_json([{'role': 'user', 'content': 'x'}], 'glm-5.1'))
async def test_AC23_4_7_records_request_and_token_usage(litellm_stub, monkeypatch): 'AC-llm.4.7'; from src.llm.base.usage import LlmUsageMeter; meter = LlmUsageMeter(); monkeypatch.setattr(streaming, 'get_usage_meter', lambda: meter); text = await accumulate_stream(stream_ai_chat([{'role': 'user', 'content': 'hello there'}], 'glm-5.1', api_key='k')); assert text == '{"ok": true}'; assert meter.requests_today == 1; assert meter.tokens_today > 0; assert 'stream_options' not in litellm_stub['kwargs']
async def test_AC23_4_5_user_qualified_model_resolves_exact_provider_with_many(litellm_stub, monkeypatch):
    'AC-llm.4.5'; from uuid import uuid4; prov_a = ProviderRef(id='a', label='a', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k1', api_base='https://a'); prov_b = ProviderRef(id='b', label='b', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k2', api_base='https://b')
    class _MultiScoped:
        async def list_providers(self): return [prov_a, prov_b]
        async def get_provider(self, provider_id): return {'a': prov_a, 'b': prov_b}.get(provider_id)
    monkeypatch.setattr(streaming, 'get_config_source', lambda *_a, **_k: _MultiScoped()); text = await accumulate_stream(stream_ai_chat([{'role': 'user', 'content': 'hi'}], 'b/glm-4.6', user_id=uuid4())); assert text == '{"ok": true}'; assert litellm_stub['kwargs']['model'] == 'openai/glm-4.6'; assert litellm_stub['kwargs']['api_base'] == 'https://b'
async def test_litellm_error_becomes_retryable_aistreamerror(monkeypatch):
    _explicit_provider(monkeypatch)
    class RateLimitError(Exception): pass
    async def boom(**kwargs): raise RateLimitError('429')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', boom)
    with pytest.raises(AIStreamError) as ei: await accumulate_stream(stream_ai_chat([{'role': 'user', 'content': 'x'}], 'glm-5.1', api_key='k'))
    assert ei.value.retryable is True
async def test_AC10_10_4_ai_provider_call_metric_emitted_on_success(litellm_stub, monkeypatch): 'AC-observability.10.4'; _explicit_provider(monkeypatch); calls: list[dict] = []; monkeypatch.setattr(streaming, 'record_ai_provider_call', lambda **kw: calls.append(kw)); text = await accumulate_stream(stream_ai_json([{'role': 'user', 'content': 'x'}], 'test-vision-model', api_key='sk-explicit')); assert text == '{"ok": true}'; assert len(calls) == 1; assert calls[0]['outcome'] == 'success'; assert calls[0]['model'] == 'test-vision-model'; assert calls[0]['duration_ms'] >= 0; assert calls[0]['provider'] in {'openai-compatible', 'anthropic-compatible', 'openrouter-compatible'}
async def test_AC10_10_4_ai_provider_call_metric_emitted_on_error(monkeypatch):
    'AC-observability.10.4'; _explicit_provider(monkeypatch); calls: list[dict] = []; monkeypatch.setattr(streaming, 'record_ai_provider_call', lambda **kw: calls.append(kw))
    async def boom_stream(*_a, **_k): raise LLMError('provider exploded', retryable=True); yield
    monkeypatch.setattr(client_mod, 'litellm_stream', lambda *a, **k: boom_stream())
    with pytest.raises(AIStreamError): await accumulate_stream(stream_ai_json([{'role': 'user', 'content': 'x'}], 'test-vision-model', api_key='sk-explicit'))
    assert len(calls) == 1; assert calls[0]['outcome'] == 'error'
