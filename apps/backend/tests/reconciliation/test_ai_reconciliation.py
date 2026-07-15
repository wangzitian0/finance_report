"""EPIC-018 Phase 3: Tests for AI-assisted reconciliation scoring.

AC-reconciliation.1803.1 AC-reconciliation.1803.2 (formerly AC18.3.2/AC18.3.3):
hybrid and feature-flagged AI scoring behavior, exercised end-to-end through
``calculate_match_score`` (not just the lower-level ``ai_semantic_score``/
``weighted_total`` helpers below).
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Direction, JournalEntry, JournalLine
from src.reconciliation import (
    DEFAULT_CONFIG,
    ReconciliationConfig,
    ai_semantic_score,
    calculate_match_score,
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


def _hybrid_band_txn_and_entry() -> tuple[AtomicTransaction, JournalEntry]:
    """Build a transaction/entry pair whose pre-AI weighted total lands in [60, 84].

    With ``DEFAULT_CONFIG`` weights (amount=0.40, date=0.25, description=0.20,
    business=0.10, history=0.05) and ``history_score_override=0.0``:
    - amount: exact match (100.00 == 100.00) -> ``score_amount`` = 100.0
    - date: same day -> ``score_date`` = 100.0
    - description: entry memo is empty -> ``score_description`` short-circuits to 0.0
    - business: no account on the journal line -> ``score_business_logic`` falls
      through to its neutral 40.0 branch for an "IN" transaction
    - history: overridden to 0.0 (skips the DB-backed ``score_pattern`` call)

    total = 100*0.40 + 100*0.25 + 0*0.20 + 40*0.10 + 0*0.05 = 40+25+0+4+0 = 69
    """
    txn = AtomicTransaction(
        description="ZQXW MERCHANT PURCHASE",
        amount=Decimal("100.00"),
        txn_date=date(2024, 1, 1),
        direction="IN",
    )
    entry = JournalEntry(
        memo="",
        entry_date=date(2024, 1, 1),
        lines=[JournalLine(amount=Decimal("100.00"), direction=Direction.DEBIT)],
    )
    return txn, entry


async def test_calculate_match_score_applies_hybrid_ai_scoring(monkeypatch, db) -> None:
    """AC-reconciliation.1803.1: with ENABLE_AI_RECONCILIATION on and a pre-AI
    weighted total in the 60-84 review band, calculate_match_score blends
    70% algorithmic + 30% AI semantic score (also proves EPIC-018 AC18.3.2).
    """
    monkeypatch.setenv("ENABLE_AI_RECONCILIATION", "true")
    txn, entry = _hybrid_band_txn_and_entry()

    pre_ai_total = weighted_total(
        {"amount": 100.0, "date": 100.0, "description": 0.0, "business": 40.0, "history": 0.0},
        DEFAULT_CONFIG,
    )
    assert pre_ai_total == 69
    assert 60 <= pre_ai_total <= 84, "fixture must land in the hybrid review band"

    mock_response = '{"similarity_score": 90, "reasoning": "close enough"}'
    mock_accumulate = AsyncMock(return_value=mock_response)
    mock_stream = MagicMock()

    with (
        patch("src.reconciliation.extension.scoring.settings") as mock_settings,
        patch("src.llm.stream_ai_json", return_value=mock_stream),
        patch("src.llm.accumulate_stream", mock_accumulate),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        candidate = await calculate_match_score(db, txn, [entry], DEFAULT_CONFIG, uuid4(), history_score_override=0.0)

    expected_score = int(round(Decimal("0.7") * pre_ai_total + Decimal("0.3") * 90, 0))
    assert expected_score == 75
    assert candidate.score == expected_score
    assert candidate.breakdown["hybrid_applied"] == 1.0
    assert candidate.breakdown["ai_semantic"] == 90.0


async def test_calculate_match_score_flag_off_skips_ai_scoring(monkeypatch, db) -> None:
    """AC-reconciliation.1803.2: with ENABLE_AI_RECONCILIATION off, the hybrid
    branch never runs — even when the pre-AI weighted total is in the 60-84
    band that would otherwise trigger it — and the LLM is never called (also
    proves EPIC-018 AC18.3.3).
    """
    monkeypatch.setenv("ENABLE_AI_RECONCILIATION", "false")
    txn, entry = _hybrid_band_txn_and_entry()

    mock_accumulate = AsyncMock(return_value='{"similarity_score": 90, "reasoning": "unused"}')
    mock_stream = MagicMock()

    with (
        patch("src.reconciliation.extension.scoring.settings") as mock_settings,
        patch("src.llm.stream_ai_json", return_value=mock_stream) as mock_stream_ai_json,
        patch("src.llm.accumulate_stream", mock_accumulate),
    ):
        mock_settings.ai_api_key = "test-key"
        mock_settings.primary_model = "test-model"
        mock_settings.ai_base_url = "https://test.api"

        candidate = await calculate_match_score(db, txn, [entry], DEFAULT_CONFIG, uuid4(), history_score_override=0.0)

        mock_stream_ai_json.assert_not_called()
        mock_accumulate.assert_not_called()

    assert candidate.score == 69
    assert "hybrid_applied" not in candidate.breakdown
    assert "ai_semantic" not in candidate.breakdown
