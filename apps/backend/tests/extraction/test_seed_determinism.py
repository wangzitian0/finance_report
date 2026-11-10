from unittest.mock import AsyncMock, MagicMock, patch; from src.config import settings; from src.extraction.extension.service import ExtractionService
async def test_extraction_forwards_configured_seed():
    'AC-extraction.116.2'; service = ExtractionService(); mock_stream = MagicMock()
    with patch.object(service, 'api_key', 'test-key'), patch.object(settings, 'ai_json_seed', 1234), patch('src.extraction.extension.service.stream_ai_json', return_value=mock_stream) as mock_stream_fn, patch('src.extraction.extension.service.accumulate_stream', AsyncMock(return_value='{"ok": true}')): result = await service._extract_json_with_model(messages=[{'role': 'user', 'content': 'x'}], model='test-model')
    assert result == {'ok': True}; assert mock_stream_fn.call_args.kwargs['seed'] == 1234
async def test_extraction_decoding_is_deterministic_by_default():
    'AC-extraction.116.3'; service = ExtractionService(); mock_stream = MagicMock()
    with patch.object(service, 'api_key', 'test-key'), patch('src.extraction.extension.service.stream_ai_json', return_value=mock_stream) as mock_stream_fn, patch('src.extraction.extension.service.accumulate_stream', AsyncMock(return_value='{"ok": true}')): await service._extract_json_with_model(messages=[{'role': 'user', 'content': 'x'}], model='test-model')
    kwargs = mock_stream_fn.call_args.kwargs; assert kwargs['temperature'] == 0.0; assert kwargs['do_sample'] is False
def test_empty_seed_env_is_treated_as_none(): 'AC-extraction.116.4'; from src.config import Settings; assert Settings(AI_JSON_SEED='').ai_json_seed is None; assert Settings(AI_JSON_SEED='   ').ai_json_seed is None; assert Settings(AI_JSON_SEED='7').ai_json_seed == 7
def test_seed_is_off_by_default(monkeypatch): 'AC-extraction.116.5'; from src.config import Settings; monkeypatch.delenv('AI_JSON_SEED', raising=False); assert Settings(_env_file=None).ai_json_seed is None
