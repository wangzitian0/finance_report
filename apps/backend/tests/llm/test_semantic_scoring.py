from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm import AIStreamError
from src.llm.extension.semantic_scoring import ai_semantic_score


@pytest.mark.parametrize(
    ("api_key", "raw_response", "stream_exc", "expected"),
    [
        ("test-key", '{"similarity_score": 92, "reasoning": "Both refer to salary"}', None, 92),
        ("test-key", '{"similarity_score": 15, "reasoning": "Completely different"}', None, 15),
        ("test-key", None, AIStreamError("API error"), 50),
        ("", None, AIStreamError("no provider configured"), 50),
        ("test-key", "  ", None, 50),
        ("test-key", '{"similarity_score": 150, "reasoning": "Over 100"}', None, 100),
    ],
)
async def test_ai_semantic_score_returns_score(api_key: str, raw_response: str | None, stream_exc: Exception | None, expected: int) -> None:
    stream_mock = MagicMock(side_effect=stream_exc) if stream_exc else MagicMock(return_value=MagicMock())
    with (
        patch("src.llm.extension.semantic_scoring.settings") as mock_settings,
        patch("src.llm.extension.semantic_scoring.stream_ai_json", stream_mock),
        patch("src.llm.extension.semantic_scoring.accumulate_stream", AsyncMock(return_value=raw_response)),
    ):
        mock_settings.ai_api_key, mock_settings.small_model, mock_settings.ai_base_url = api_key, "test-model", "https://test.api"
        assert await ai_semantic_score("test prompt") == expected
