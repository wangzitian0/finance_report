"""AC13.16: Deterministic decoding for statement extraction (#989).

Same source must not sometimes reconcile and sometimes not. Extraction already
pins temperature 0 / do_sample False; this adds a configurable request ``seed``
so the model decodes reproducibly. These tests assert the seed is threaded from
settings into the streaming call.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.config import settings
from src.services.extraction import ExtractionService


async def test_extraction_forwards_configured_seed():
    """AC13.16.2: _extract_json_with_models forwards settings.ai_json_seed."""
    service = ExtractionService()

    mock_stream = MagicMock()
    with (
        patch.object(service, "api_key", "test-key"),
        patch.object(service, "base_url", "https://test.api"),
        patch.object(settings, "ai_json_seed", 1234),
        patch("src.services.extraction.stream_ai_json", return_value=mock_stream) as mock_stream_fn,
        patch("src.services.extraction.accumulate_stream", AsyncMock(return_value='{"ok": true}')),
    ):
        result = await service._extract_json_with_models(
            messages=[{"role": "user", "content": "x"}],
            models=["test-model"],
            prompt="p",
            institution="DBS",
            file_type="pdf",
            return_raw=False,
            has_content=True,
            has_url=False,
        )

    assert result == {"ok": True}
    assert mock_stream_fn.call_args.kwargs["seed"] == 1234


async def test_extraction_decoding_is_deterministic_by_default():
    """AC13.16.3: temperature 0 / do_sample False are pinned alongside the seed."""
    service = ExtractionService()

    mock_stream = MagicMock()
    with (
        patch.object(service, "api_key", "test-key"),
        patch.object(service, "base_url", "https://test.api"),
        patch("src.services.extraction.stream_ai_json", return_value=mock_stream) as mock_stream_fn,
        patch("src.services.extraction.accumulate_stream", AsyncMock(return_value='{"ok": true}')),
    ):
        await service._extract_json_with_models(
            messages=[{"role": "user", "content": "x"}],
            models=["test-model"],
            prompt="p",
            institution="DBS",
            file_type="pdf",
            return_raw=False,
            has_content=True,
            has_url=False,
        )

    kwargs = mock_stream_fn.call_args.kwargs
    assert kwargs["temperature"] == 0.0
    assert kwargs["do_sample"] is False


def test_empty_seed_env_is_treated_as_none():
    """AC13.16.4: AI_JSON_SEED= (empty) parses as None instead of raising, so the
    seed can be omitted for providers that reject it (#989)."""
    from src.config import Settings

    assert Settings(AI_JSON_SEED="").ai_json_seed is None
    assert Settings(AI_JSON_SEED="   ").ai_json_seed is None
    assert Settings(AI_JSON_SEED="7").ai_json_seed == 7


def test_seed_is_off_by_default(monkeypatch):
    """AC13.16.5: the seed is off (None) by default, so it is never sent to
    providers that reject unknown params (e.g. glm-4.6v returns HTTP 400) unless
    explicitly opted in for a seed-supporting model (#989)."""
    from src.config import Settings

    # Ignore any AI_JSON_SEED in the developer's real environment / .env.
    monkeypatch.delenv("AI_JSON_SEED", raising=False)
    assert Settings(_env_file=None).ai_json_seed is None
