"""Promotion gate: the deterministic trust boundary (EPIC-018 AC18.13, issue #930).

Vision Axiom B requires confidence to be *co-equal with traceability* — it must
gate what becomes truth, not merely be displayed. A versioned fact becomes
authoritative ONLY IF its deterministic invariants pass AND confidence meets the
named threshold; otherwise it stays a candidate and is escalated. AI/Derived
versions may propose; the gate (strong code) disposes.
"""

from decimal import Decimal

from src.audit.promotion import (
    RECONCILIATION_AUTO_ACCEPT_SCORE,
    RECONCILIATION_REVIEW_SCORE,
    STATEMENT_BALANCE_TOLERANCE,
    InvariantResult,
    PromotionDecision,
    evaluate_promotion,
    tier_rank,
)


def test_AC18_13_1_failed_invariant_is_rejected_with_queryable_reason():
    """AC18.13.1: A failed deterministic invariant is REJECTED (never authoritative), with a queryable reason."""
    verdict = evaluate_promotion(
        [
            InvariantResult(
                name="balance_chain",
                passed=False,
                delta=Decimal("0.05"),
                tolerance=STATEMENT_BALANCE_TOLERANCE,
            )
        ],
        confidence_rank=tier_rank("TRUSTED"),  # even max confidence cannot override a failed invariant
        min_confidence=tier_rank("HIGH"),
    )
    assert verdict.decision is PromotionDecision.REJECTED
    assert verdict.is_authoritative is False
    assert verdict.failed_invariant == "balance_chain"
    assert verdict.detail == {"delta": "0.05", "tolerance": "0.001"}


def test_AC18_13_2_invariants_pass_but_low_confidence_is_review():
    """AC18.13.2: Invariants pass but confidence below threshold -> REVIEW candidate, not authoritative."""
    verdict = evaluate_promotion(
        [InvariantResult(name="balance_chain", passed=True)],
        confidence_rank=tier_rank("LOW"),
        min_confidence=tier_rank("HIGH"),
    )
    assert verdict.decision is PromotionDecision.REVIEW
    assert verdict.is_authoritative is False
    assert verdict.invariants_pass is True
    assert verdict.confidence_ok is False
    assert "threshold" in verdict.reason


def test_AC18_13_3_invariants_pass_and_confidence_met_is_authoritative():
    """AC18.13.3: Invariants pass AND confidence >= threshold -> AUTHORITATIVE. Same contract for tier and score."""
    by_tier = evaluate_promotion(
        [InvariantResult(name="balance_chain", passed=True)],
        confidence_rank=tier_rank("HIGH"),
        min_confidence=tier_rank("HIGH"),
    )
    assert by_tier.decision is PromotionDecision.AUTHORITATIVE
    assert by_tier.is_authoritative is True

    # The same gate carries the reconciliation score decision: 70 < 85 -> review, 90 -> authoritative.
    review = evaluate_promotion(
        [InvariantResult(name="entry_balanced", passed=True)],
        confidence_rank=70,
        min_confidence=RECONCILIATION_AUTO_ACCEPT_SCORE,
    )
    assert review.decision is PromotionDecision.REVIEW
    cleared = evaluate_promotion(
        [InvariantResult(name="entry_balanced", passed=True)],
        confidence_rank=90,
        min_confidence=RECONCILIATION_AUTO_ACCEPT_SCORE,
    )
    assert cleared.decision is PromotionDecision.AUTHORITATIVE


def test_AC18_13_4_thresholds_are_centrally_owned_and_consumed_by_services():
    """AC18.13.4: The previously-scattered thresholds are named, centrally owned, and consumed by the services."""
    assert STATEMENT_BALANCE_TOLERANCE == Decimal("0.001")
    assert RECONCILIATION_AUTO_ACCEPT_SCORE == 85
    assert RECONCILIATION_REVIEW_SCORE == 60

    import src.reconciliation as reconciliation
    from src.extraction.extension import statement_validation

    assert statement_validation.BALANCE_TOLERANCE is STATEMENT_BALANCE_TOLERANCE
    assert reconciliation.DEFAULT_CONFIG.auto_accept == RECONCILIATION_AUTO_ACCEPT_SCORE
    assert reconciliation.DEFAULT_CONFIG.pending_review == RECONCILIATION_REVIEW_SCORE
