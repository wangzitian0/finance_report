from decimal import Decimal

import src.reconciliation as reconciliation
from src.audit.promotion import RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE, STATEMENT_BALANCE_TOLERANCE, InvariantResult, PromotionDecision, evaluate_promotion, tier_rank
from src.extraction.extension import statement_validation


def test_AC18_13_promotion_gate_verdicts_and_thresholds() -> None:
    rejected = evaluate_promotion([InvariantResult(name="balance_chain", passed=False, delta=Decimal("0.05"), tolerance=STATEMENT_BALANCE_TOLERANCE)], confidence_rank=tier_rank("TRUSTED"), min_confidence=tier_rank("HIGH"))
    low_conf = evaluate_promotion([InvariantResult(name="balance_chain", passed=True)], confidence_rank=tier_rank("LOW"), min_confidence=tier_rank("HIGH"))
    auth_tier = evaluate_promotion([InvariantResult(name="balance_chain", passed=True)], confidence_rank=tier_rank("HIGH"), min_confidence=tier_rank("HIGH"))
    score_rev = evaluate_promotion([InvariantResult(name="entry_balanced", passed=True)], confidence_rank=70, min_confidence=RECONCILIATION_AUTO_ACCEPT_SCORE)
    score_ok = evaluate_promotion([InvariantResult(name="entry_balanced", passed=True)], confidence_rank=90, min_confidence=RECONCILIATION_AUTO_ACCEPT_SCORE)
    assert (
        rejected.decision, rejected.is_authoritative, rejected.failed_invariant, rejected.detail,
        low_conf.decision, low_conf.is_authoritative, low_conf.invariants_pass, low_conf.confidence_ok, "threshold" in low_conf.reason,
        auth_tier.decision, auth_tier.is_authoritative, score_rev.decision, score_ok.decision,
        STATEMENT_BALANCE_TOLERANCE, RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE,
        statement_validation.BALANCE_TOLERANCE is STATEMENT_BALANCE_TOLERANCE, reconciliation.DEFAULT_CONFIG.auto_accept, reconciliation.DEFAULT_CONFIG.pending_review,
    ) == (
        PromotionDecision.REJECTED, False, "balance_chain", {"delta": "0.05", "tolerance": "0.001"},
        PromotionDecision.REVIEW, False, True, False, True,
        PromotionDecision.AUTHORITATIVE, True, PromotionDecision.REVIEW, PromotionDecision.AUTHORITATIVE,
        Decimal("0.001"), 85, 60, True, RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE,
    )
