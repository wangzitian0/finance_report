'EPIC-023'; from __future__ import annotations; from pathlib import Path; import pytest; import src.llm.extension.client as client_mod; from src.llm import accumulate_stream; from src.llm.base import DecodeParams, LLMError, ProtocolFamily, ProviderRef; from src.llm.extension.cassette import CassetteMiss, CassetteMode, CassetteStore, CassetteTag, fingerprint; from src.llm.extension.client import CassetteOptions, litellm_stream as _typed_litellm_stream; FIXTURE_CASSETTE_DIR = Path(__file__).resolve().parents[4] / 'common' / 'testing' / 'fixtures' / 'llm_cassettes'; litellm_stream = lambda messages, *, provider, model_id, max_tokens=None, temperature=None, cassette_store=None, cassette_mode=None, cassette_tag=CassetteTag.FLOW_ONLY, cassette_validator=None: _typed_litellm_stream(messages, provider=provider, model_id=model_id, decode=DecodeParams(max_tokens=max_tokens, temperature=temperature), cassette=CassetteOptions(store=cassette_store, mode=cassette_mode, tag=cassette_tag, validator=cassette_validator)); _TEXT_MESSAGES = [{'role': 'system', 'content': 'Extract transactions as JSON.'}, {'role': 'user', 'content': 'Statement S-0001 closing balance 100.00'}]; _TEXT_DECODE = {'temperature': 0.0, 'max_tokens': 512}; _TEXT_FROZEN = '{"transactions": [], "closing_balance": "100.00"}'; _VISION_MESSAGES = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Read this statement image and return JSON.'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC'}}]}]; _VISION_DECODE = {'temperature': 0.0}; _VISION_FROZEN = '{"transactions": [], "closing_balance": "250.00"}'; _provider = lambda: ProviderRef(id='env', label='zai', protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key='k', api_base='https://api.z.ai')
class _Delta:
    def __init__(self, content: str | None) -> None: self.content = content
class _Choice:
    def __init__(self, content: str | None) -> None: self.delta = _Delta(content)
class _Chunk:
    def __init__(self, content: str | None) -> None: self.choices = [_Choice(content)]
def _fake_stream(*pieces: str):
    async def fake_acompletion(**kwargs):
        async def gen():
            for piece in pieces: yield _Chunk(piece)
        return gen()
    return fake_acompletion
@pytest.fixture
def committed_store() -> CassetteStore: return CassetteStore(directory=FIXTURE_CASSETTE_DIR)
async def test_AC23_6_1_replay_synthesises_stream_from_frozen_text_cassette(monkeypatch, committed_store):
    'AC-llm.6.1'
    async def explode(**kwargs): raise AssertionError('replay must not call litellm')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', explode); chunks = [c async for c in litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', temperature=0.0, max_tokens=512, cassette_store=committed_store, cassette_mode=CassetteMode.REPLAY)]; assert ''.join(chunks) == _TEXT_FROZEN; again = await accumulate_stream(litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', temperature=0.0, max_tokens=512, cassette_store=committed_store, cassette_mode=CassetteMode.REPLAY)); assert again == _TEXT_FROZEN
async def test_AC23_6_1_replay_vision_cassette_synthesises_stream(monkeypatch, committed_store):
    'AC-llm.6.1'
    async def explode(**kwargs): raise AssertionError('replay must not call litellm')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', explode); text = await accumulate_stream(litellm_stream(_VISION_MESSAGES, provider=_provider(), model_id='test-vision-model', temperature=0.0, cassette_store=committed_store, cassette_mode=CassetteMode.REPLAY)); assert text == _VISION_FROZEN
async def test_AC23_6_2_replay_miss_is_hard_failure(monkeypatch, tmp_path):
    'AC-llm.6.2'
    async def explode(**kwargs): raise AssertionError('replay must not call litellm')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', explode); empty_store = CassetteStore(directory=tmp_path / 'empty')
    with pytest.raises(CassetteMiss) as ei:
        async for _ in litellm_stream([{'role': 'user', 'content': 'no cassette for this'}], provider=_provider(), model_id='glm-5.1', cassette_store=empty_store, cassette_mode=CassetteMode.REPLAY): pass
    assert ei.value.scene == 'text'
async def test_AC23_6_3_record_accumulates_and_writes_cassette(monkeypatch, tmp_path): 'AC-llm.6.3'; monkeypatch.setattr(client_mod.litellm, 'acompletion', _fake_stream('{"a"', ':1', '}')); store = CassetteStore(directory=tmp_path / 'c'); out = await accumulate_stream(litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', temperature=0.0, max_tokens=512, cassette_store=store, cassette_mode=CassetteMode.RECORD)); assert out == '{"a":1}'; key = fingerprint(role='text', messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE); cassette = store.get(key); assert cassette is not None; assert cassette.response['stream_text'] == '{"a":1}'; assert cassette.role == 'text'
async def test_AC23_6_3_record_is_idempotent(monkeypatch, tmp_path):
    'AC-llm.6.3'; monkeypatch.setattr(client_mod.litellm, 'acompletion', _fake_stream('frozen')); store = CassetteStore(directory=tmp_path / 'c'); key = fingerprint(role='text', messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE)
    async def record_once(): await accumulate_stream(litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', temperature=0.0, max_tokens=512, cassette_store=store, cassette_mode=CassetteMode.RECORD))
    await record_once(); first = store.get(key); first_path = (tmp_path / 'c' / f'{key}.json').read_text(encoding='utf-8'); await record_once(); assert (tmp_path / 'c' / f'{key}.json').read_text(encoding='utf-8') == first_path; assert first is not None
async def test_AC23_6_4_off_mode_passes_stream_through_untouched(monkeypatch, tmp_path): 'AC-llm.6.4'; monkeypatch.setattr(client_mod.litellm, 'acompletion', _fake_stream('Hel', '', 'lo')); store = CassetteStore(directory=tmp_path / 'c'); chunks = [c async for c in litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', cassette_store=store, cassette_mode=CassetteMode.OFF)]; assert chunks == ['Hel', 'lo']; assert not (tmp_path / 'c').exists() or list((tmp_path / 'c').glob('*.json')) == []
async def test_AC23_6_4_off_mode_normalises_provider_error(monkeypatch):
    'AC-llm.6.4'
    async def boom(**kwargs): raise ValueError('bad request')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', boom)
    with pytest.raises(LLMError):
        async for _ in litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', cassette_mode=CassetteMode.OFF): pass
def test_AC23_6_5_role_derivation_text_vs_vision_distinct_keys(): 'AC-llm.6.5'; assert client_mod._stream_role(_VISION_MESSAGES) == 'vision'; assert client_mod._stream_role(_TEXT_MESSAGES) == 'text'; k_text = fingerprint(role='text', messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE); k_vision = fingerprint(role='vision', messages=_VISION_MESSAGES, decode_params=_VISION_DECODE); assert k_text != k_vision
async def test_AC23_6_5_model_id_swap_resolves_same_cassette(monkeypatch, committed_store):
    'AC-llm.6.5'
    async def explode(**kwargs): raise AssertionError('replay must not call litellm')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', explode); out_a = await accumulate_stream(litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', temperature=0.0, max_tokens=512, cassette_store=committed_store, cassette_mode=CassetteMode.REPLAY)); out_b = await accumulate_stream(litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.2', temperature=0.0, max_tokens=512, cassette_store=committed_store, cassette_mode=CassetteMode.REPLAY)); assert out_a == out_b == _TEXT_FROZEN
async def test_AC23_6_3_record_correctness_requires_validator(monkeypatch, tmp_path):
    'AC-llm.6.3'; from src.llm.extension.cassette import CassetteValidationError; monkeypatch.setattr(client_mod.litellm, 'acompletion', _fake_stream('anything')); store = CassetteStore(directory=tmp_path / 'c')
    with pytest.raises(CassetteValidationError):
        async for _ in litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', cassette_store=store, cassette_mode=CassetteMode.RECORD, cassette_tag=CassetteTag.CORRECTNESS): pass
async def test_AC23_6_3_record_correctness_validated_freezes_text(monkeypatch, tmp_path): 'AC-llm.6.3'; monkeypatch.setattr(client_mod.litellm, 'acompletion', _fake_stream('{"closing_balance":', ' "100.00"}')); store = CassetteStore(directory=tmp_path / 'c'); validator = lambda response: response['stream_text'] == '{"closing_balance": "100.00"}'; out = await accumulate_stream(litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', temperature=0.0, max_tokens=512, cassette_store=store, cassette_mode=CassetteMode.RECORD, cassette_tag=CassetteTag.CORRECTNESS, cassette_validator=validator)); assert out == '{"closing_balance": "100.00"}'; key = fingerprint(role='text', messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE); assert store.get(key) is not None
async def test_AC23_6_3_record_correctness_refuses_wrong_answer(monkeypatch, tmp_path):
    'AC-llm.6.3'; from src.llm.extension.cassette import CassetteValidationError; monkeypatch.setattr(client_mod.litellm, 'acompletion', _fake_stream('wrong answer')); store = CassetteStore(directory=tmp_path / 'c')
    with pytest.raises(CassetteValidationError):
        async for _ in litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', cassette_store=store, cassette_mode=CassetteMode.RECORD, cassette_tag=CassetteTag.CORRECTNESS, cassette_validator=lambda _response: False): pass
    key = fingerprint(role='text', messages=_TEXT_MESSAGES, decode_params=_TEXT_DECODE); assert store.get(key) is None
async def test_AC23_6_3_record_correctness_validator_error_refuses(monkeypatch, tmp_path):
    'AC-llm.6.3'; from src.llm.extension.cassette import CassetteValidationError
    def boom(_response: dict) -> bool: raise RuntimeError('validator blew up')
    monkeypatch.setattr(client_mod.litellm, 'acompletion', _fake_stream('anything')); store = CassetteStore(directory=tmp_path / 'c')
    with pytest.raises(CassetteValidationError):
        async for _ in litellm_stream(_TEXT_MESSAGES, provider=_provider(), model_id='glm-5.1', cassette_store=store, cassette_mode=CassetteMode.RECORD, cassette_tag=CassetteTag.CORRECTNESS, cassette_validator=boom): pass
