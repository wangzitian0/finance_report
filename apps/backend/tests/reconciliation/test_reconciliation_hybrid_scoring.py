"""EPIC-018 Phase 3: hybrid + feature-flagged AI-reconciliation scoring.

AC-reconciliation.1803.1 / AC-reconciliation.1803.2 (formerly AC18.3.2/
AC18.3.3), exercised end-to-end through ``calculate_match_score``.

Kept in a separate file from ``test_ai_reconciliation.py`` (which exercises
the lower-level AI-provider streaming call directly, now owned by the
``llm`` package) and mocks at the ``ai_semantic_score`` call boundary
instead: this package (``reconciliation``) is declared ``CODE-ONLY``, and
``common/meta/extension/authority_classifier.py`` classifies a test FILE as
an LLM test — file-level, not per-function — if it contains any of a
handful of literal provider-call markers anywhere in the file (see
``LLM_TEST_MARKERS`` in that module). A file mixing these two deterministic
gating/formula tests with a literal low-level provider-call mock would
misclassify this package's detected authority band and trip
``tools/check_authority_reconcile.py``'s CODE-ONLY-vs-detected-LLM check,
even though what's actually under test here (the 60-84 band gate, the
0.7/0.3 blend, the feature flag) is ordinary deterministic code — the AI
scorer is a black box these tests treat as an opaque, mocked dependency.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Direction, JournalEntry, JournalLine
from src.reconciliation import DEFAULT_CONFIG, calculate_match_score, weighted_total


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

    mock_ai_score = AsyncMock(return_value=90)

    with patch("src.reconciliation.extension.matching.ai_semantic_score", mock_ai_score):
        candidate = await calculate_match_score(db, txn, [entry], DEFAULT_CONFIG, uuid4(), history_score_override=0.0)

    expected_score = int(round(Decimal("0.7") * pre_ai_total + Decimal("0.3") * 90, 0))
    assert expected_score == 75
    assert candidate.score == expected_score
    assert candidate.breakdown["hybrid_applied"] == 1.0
    assert candidate.breakdown["ai_semantic"] == 90.0
    mock_ai_score.assert_awaited_once()


async def test_calculate_match_score_flag_off_skips_ai_scoring(monkeypatch, db) -> None:
    """AC-reconciliation.1803.2: with ENABLE_AI_RECONCILIATION off, the hybrid
    branch never runs — even when the pre-AI weighted total is in the 60-84
    band that would otherwise trigger it — and the AI scorer is never called
    (also proves EPIC-018 AC18.3.3).
    """
    monkeypatch.setenv("ENABLE_AI_RECONCILIATION", "false")
    txn, entry = _hybrid_band_txn_and_entry()

    mock_ai_score = AsyncMock(return_value=90)

    with patch("src.reconciliation.extension.matching.ai_semantic_score", mock_ai_score):
        candidate = await calculate_match_score(db, txn, [entry], DEFAULT_CONFIG, uuid4(), history_score_override=0.0)
        mock_ai_score.assert_not_called()

    assert candidate.score == 69
    assert "hybrid_applied" not in candidate.breakdown
    assert "ai_semantic" not in candidate.breakdown
