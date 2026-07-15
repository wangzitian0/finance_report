"""Tests for the generic prompt-in/score-out semantic scoring helper.

Moved from ``apps/backend/tests/reconciliation/test_ai_reconciliation.py``
(EPIC-018 Phase 3) together with ``ai_semantic_score`` itself: the function
is a genuine LLM call, which cannot live in ``reconciliation`` (declared
``CODE-ONLY`` — see ``common/meta/readme.md``'s "Cross-tier MUST rules", rule
2). See ``common/llm/contract.py``'s ``AC-llm.semantic-scoring.1`` for the
roadmap entry (was AC18.3.1); reconciliation's hybrid-scoring/feature-flag
behavior (AC18.3.2/AC18.3.3) stays reconciliation's own concern and is not
touched here.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.llm.extension.semantic_scoring import ai_semantic_score


async def test_ai_semantic_score_returns_score():
    """AC-llm.semantic-scoring.1: ai_semantic_score returns similarity score for matching descriptions."""
    mock_response = '{"similarity_score": 92, "reasoning": "Both refer to salary"}'

    mock_accumulate = AsyncMock(return_value=mock_response)
    mock_stream = MagicMock()

    with (
        patch("src.llm.extension.semantic_scoring.settings") as mock_settings,
        patch(
            "src.llm.extension.semantic_scoring.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.extension.semantic_scoring.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score('Bank Transaction: "SALARY ACME CORP"\nJournal Entry: "Monthly salary payment"')
        assert score == 92


async def test_ai_semantic_score_returns_low_for_unrelated():
    """ai_semantic_score returns low score for unrelated descriptions."""
    mock_response = '{"similarity_score": 15, "reasoning": "Completely different"}'

    mock_accumulate = AsyncMock(return_value=mock_response)
    mock_stream = MagicMock()

    with (
        patch("src.llm.extension.semantic_scoring.settings") as mock_settings,
        patch(
            "src.llm.extension.semantic_scoring.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.extension.semantic_scoring.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score(
            'Bank Transaction: "COFFEE SHOP PURCHASE"\nJournal Entry: "Car insurance premium"'
        )
        assert score == 15


async def test_ai_semantic_score_fallback_on_error():
    """ai_semantic_score falls back to 50 on any error."""
    from src.llm import AIStreamError

    mock_stream = MagicMock(side_effect=AIStreamError("API error"))

    with (
        patch("src.llm.extension.semantic_scoring.settings") as mock_settings,
        patch(
            "src.llm.extension.semantic_scoring.stream_ai_json",
            mock_stream,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score("test prompt")
        assert score == 50


async def test_ai_semantic_score_no_api_key_returns_50():
    """When no provider is configured, the stream call fails and we fall back to neutral.

    ``ai_semantic_score`` has no explicit API-key precheck — it always calls
    ``stream_ai_json`` and only falls back on the caught exception types.
    ``stream_ai_json`` resolves providers via
    ``src.llm.extension.streaming.get_config_source(...).list_providers()``
    (env/DB-backed), not directly off ``settings.ai_api_key``, so patching
    ``settings`` alone does not stop this test from reaching the real
    provider-resolution path — it must mock ``stream_ai_json`` itself to stay
    deterministic and never risk a real network call (flagged in review on
    PR #1861).
    """
    from src.llm import AIStreamError

    mock_stream = MagicMock(side_effect=AIStreamError("no provider configured"))

    with (
        patch("src.llm.extension.semantic_scoring.settings") as mock_settings,
        patch("src.llm.extension.semantic_scoring.stream_ai_json", mock_stream),
    ):
        mock_settings.ai_api_key = ""

        score = await ai_semantic_score("test prompt")
        assert score == 50


async def test_ai_semantic_score_empty_response_returns_50():
    """Empty AI responses fall back to neutral score."""
    mock_accumulate = AsyncMock(return_value="  ")
    mock_stream = MagicMock()

    with (
        patch("src.llm.extension.semantic_scoring.settings") as mock_settings,
        patch(
            "src.llm.extension.semantic_scoring.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.extension.semantic_scoring.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score("test prompt")
        assert score == 50


async def test_ai_semantic_score_clamps_to_range():
    """Score is clamped to 0-100 range."""
    mock_response = '{"similarity_score": 150, "reasoning": "Over 100"}'

    mock_accumulate = AsyncMock(return_value=mock_response)
    mock_stream = MagicMock()

    with (
        patch("src.llm.extension.semantic_scoring.settings") as mock_settings,
        patch(
            "src.llm.extension.semantic_scoring.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.extension.semantic_scoring.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score("test prompt")
        assert score == 100
