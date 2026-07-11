"""EPIC-018 Phase 3: Tests for AI-assisted reconciliation scoring.

AC18.3.2 AC18.3.3: Hybrid and feature-flagged AI scoring behavior.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.reconciliation import (
    ReconciliationConfig,
    ai_semantic_score,
    weighted_total,
)


def _default_config() -> ReconciliationConfig:
    """Create a ReconciliationConfig with default weights for testing."""
    return ReconciliationConfig(
        weight_amount=Decimal("0.40"),
        weight_date=Decimal("0.20"),
        weight_description=Decimal("0.20"),
        weight_business=Decimal("0.15"),
        weight_history=Decimal("0.05"),
        auto_accept=85,
        pending_review=60,
        amount_percent=Decimal("5.0"),
        amount_absolute=Decimal("1.00"),
        date_days=3,
    )


async def test_ai_semantic_score_returns_score():
    """AC18.3.1: ai_semantic_score returns similarity score for matching descriptions."""
    mock_response = '{"similarity_score": 92, "reasoning": "Both refer to salary"}'

    mock_accumulate = AsyncMock(return_value=mock_response)
    mock_stream = MagicMock()

    with (
        patch("src.reconciliation.extension.scoring.settings") as mock_settings,
        patch(
            "src.llm.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score(
            txn_description="SALARY ACME CORP",
            entry_memo="Monthly salary payment",
            date_diff_days=0,
            amount_match_pct=100.0,
        )
        assert score == 92


async def test_ai_semantic_score_returns_low_for_unrelated():
    """ai_semantic_score returns low score for unrelated descriptions."""
    mock_response = '{"similarity_score": 15, "reasoning": "Completely different"}'

    mock_accumulate = AsyncMock(return_value=mock_response)
    mock_stream = MagicMock()

    with (
        patch("src.reconciliation.extension.scoring.settings") as mock_settings,
        patch(
            "src.llm.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score(
            txn_description="COFFEE SHOP PURCHASE",
            entry_memo="Car insurance premium",
            date_diff_days=15,
            amount_match_pct=30.0,
        )
        assert score == 15


async def test_ai_semantic_score_fallback_on_error():
    """ai_semantic_score falls back to 50 on any error."""
    from src.llm import AIStreamError

    mock_stream = MagicMock(side_effect=AIStreamError("API error"))

    with (
        patch("src.reconciliation.extension.scoring.settings") as mock_settings,
        patch(
            "src.llm.stream_ai_json",
            mock_stream,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score(
            txn_description="test",
            entry_memo="test",
            date_diff_days=0,
            amount_match_pct=100.0,
        )
        assert score == 50


async def test_ai_semantic_score_no_api_key_returns_50():
    """When no API key is configured, fall back to neutral score."""
    with patch("src.reconciliation.extension.scoring.settings") as mock_settings:
        mock_settings.ai_api_key = ""

        score = await ai_semantic_score(
            txn_description="test",
            entry_memo="test",
            date_diff_days=0,
            amount_match_pct=100.0,
        )
        assert score == 50


async def test_ai_semantic_score_empty_response_returns_50():
    """Empty AI responses fall back to neutral score."""
    mock_accumulate = AsyncMock(return_value="  ")
    mock_stream = MagicMock()

    with (
        patch("src.reconciliation.extension.scoring.settings") as mock_settings,
        patch(
            "src.llm.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score(
            txn_description="test",
            entry_memo="test",
            date_diff_days=0,
            amount_match_pct=100.0,
        )
        assert score == 50


async def test_ai_semantic_score_clamps_to_range():
    """Score is clamped to 0-100 range."""
    mock_response = '{"similarity_score": 150, "reasoning": "Over 100"}'

    mock_accumulate = AsyncMock(return_value=mock_response)
    mock_stream = MagicMock()

    with (
        patch("src.reconciliation.extension.scoring.settings") as mock_settings,
        patch(
            "src.llm.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.llm.accumulate_stream",
            mock_accumulate,
        ),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        score = await ai_semantic_score(
            txn_description="test",
            entry_memo="test",
            date_diff_days=0,
            amount_match_pct=100.0,
        )
        assert score == 100


def test_weighted_total_computes_correctly():
    """Verify weighted_total formula produces correct integer result."""
    config = _default_config()
    scores = {
        "amount": 100.0,
        "date": 80.0,
        "description": 60.0,
        "business": 50.0,
        "history": 0.0,
    }
    total = weighted_total(scores, config)
    assert isinstance(total, int)
    assert total > 0
    # 100*0.4 + 80*0.2 + 60*0.2 + 50*0.15 + 0*0.05 = 40+16+12+7.5+0 = 75.5 ≈ 76
    assert total == 76


def test_weighted_total_all_zeros():
    """Weighted total of all zeros is zero."""
    config = _default_config()
    scores = {
        "amount": 0.0,
        "date": 0.0,
        "description": 0.0,
        "business": 0.0,
        "history": 0.0,
    }
    total = weighted_total(scores, config)
    assert total == 0
