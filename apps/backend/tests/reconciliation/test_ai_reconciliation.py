"""EPIC-018 Phase 3: Tests for AI-assisted reconciliation scoring.

The ``calculate_match_score``-level hybrid/feature-flag behavior
(AC-reconciliation.1803.1/.2, formerly AC18.3.2/AC18.3.3) lives in
``test_reconciliation_hybrid_scoring.py`` instead of here — kept out of this
file specifically so a package-wide LLM-test-marker scan (this file used to
mock ``stream_ai_json`` directly) doesn't misclassify those two deterministic
gating/formula ACs as LLM tests.

``ai_semantic_score`` itself (was AC18.3.1) moved to the ``llm`` package
(a genuine LLM call cannot live in this CODE-ONLY package — see
``common/meta/readme.md``'s Cross-tier MUST rule 2); its tests moved to
``apps/backend/tests/llm/test_semantic_scoring.py``.
"""

from decimal import Decimal

from src.reconciliation import ReconciliationConfig, weighted_total


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
