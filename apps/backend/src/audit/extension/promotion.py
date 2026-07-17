"""Deterministic policy that folds invariant observations into promotion."""

from __future__ import annotations

from collections.abc import Sequence

from src.audit.base.promotion import (
    InvariantResult,
    PromotionDecision,
    PromotionVerdict,
)

_TIER_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "TRUSTED": 3}


def tier_rank(tier: str | None) -> int:
    """Numeric rank of a confidence tier (unknown/None -> lowest)."""
    return _TIER_RANK.get((tier or "").upper(), 0)


def evaluate_promotion(
    invariants: Sequence[InvariantResult],
    *,
    confidence_rank: int,
    min_confidence: int,
    confidence_label: str = "confidence",
) -> PromotionVerdict:
    """Reject failed invariants before applying the confidence threshold."""
    failed = next((invariant for invariant in invariants if not invariant.passed), None)
    if failed is not None:
        detail: dict[str, str] = {}
        if failed.delta is not None and failed.tolerance is not None:
            detail = {"delta": str(failed.delta), "tolerance": str(failed.tolerance)}
        return PromotionVerdict(
            decision=PromotionDecision.REJECTED,
            invariants_pass=False,
            confidence_ok=confidence_rank >= min_confidence,
            reason=f"invariant '{failed.name}' failed",
            failed_invariant=failed.name,
            detail=detail,
        )

    if confidence_rank < min_confidence:
        return PromotionVerdict(
            decision=PromotionDecision.REVIEW,
            invariants_pass=True,
            confidence_ok=False,
            reason=f"{confidence_label} {confidence_rank} below promotion threshold {min_confidence}",
        )

    return PromotionVerdict(
        decision=PromotionDecision.AUTHORITATIVE,
        invariants_pass=True,
        confidence_ok=True,
        reason="invariants pass and confidence meets threshold",
    )
