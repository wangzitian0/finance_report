'AC-llm.4.5 EPIC-023'; from __future__ import annotations; import contextlib; from uuid import uuid4; import pytest; from src.extraction.extension import service as extraction_mod; from src.extraction.extension.service import ExtractionService; pytestmark = pytest.mark.no_db
async def test_AC23_4_5_extraction_threads_user_id_to_stream() -> None:
    captured: dict[str, object] = {}
    async def fake_stream_ai_json(messages, model, *, user_id=None, **_kw): captured['user_id'] = user_id; yield '{"transactions": [], "institution": "X"}'
    original = extraction_mod.stream_ai_json; extraction_mod.stream_ai_json = fake_stream_ai_json
    try:
        service = ExtractionService(); uid = uuid4()
        with contextlib.suppress(Exception): await service._extract_json_with_model(messages=[{'role': 'user', 'content': 'x'}], model='test-model', user_id=uid)
    finally: extraction_mod.stream_ai_json = original
    assert captured.get('user_id') == uid
