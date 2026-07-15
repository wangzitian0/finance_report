"""Promotion gate: the deterministic trust boundary (#930, Axiom B made load-bearing).

A versioned fact (#918) carrying a provenance (#888) and a measured confidence
(#913) becomes **authoritative only if** its deterministic invariant(s) pass
**and** its confidence meets the named threshold; otherwise it stays a
non-authoritative candidate and is escalated for review:

    authoritative  ⇔  invariants_pass  ∧  confidence ≥ τ

AI / Derived versions may only *propose*; this gate (strong code) *disposes*. The
named thresholds below are the single owner of what were magic numbers scattered
across services (statement balance tolerance, reconciliation auto-accept/review).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

# --- Named, centrally-owned thresholds (consolidates the scattered magic numbers) ---
STATEMENT_BALANCE_TOLERANCE = Decimal("0.001")
RECONCILIATION_AUTO_ACCEPT_SCORE = 85
RECONCILIATION_REVIEW_SCORE = 60

# Confidence tier ranks, lowest -> highest trust (the #913 axis), so a tier can be
# compared against a minimum-tier threshold with the same contract as a score.
_TIER_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "TRUSTED": 3}


def tier_rank(tier: str | None) -> int:
    """Numeric rank of a confidence tier (unknown/None -> lowest)."""
    return _TIER_RANK.get((tier or "").upper(), 0)


class PromotionDecision(StrEnum):
    """What the gate decided a version may become."""

    AUTHORITATIVE = "authoritative"  # invariants pass AND confidence >= threshold
    REVIEW = "review"  # invariants pass but confidence below threshold -> escalate
    REJECTED = "rejected"  # a deterministic invariant failed -> cannot become truth


@dataclass(frozen=True)
class InvariantResult:
    """One deterministic invariant the gate consumes (e.g. the balance-chain check)."""

    name: str
    passed: bool
    delta: Decimal | None = None  # computed magnitude, when the check is a tolerance comparison
    tolerance: Decimal | None = None  # the tolerance it was checked against


@dataclass(frozen=True)
class PromotionVerdict:
    """The gate's decision plus a queryable escalation reason (not a bare status)."""

    decision: PromotionDecision
    invariants_pass: bool
    confidence_ok: bool
    reason: str
    failed_invariant: str | None = None
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def is_authoritative(self) -> bool:
        return self.decision is PromotionDecision.AUTHORITATIVE


def evaluate_promotion(
    invariants: Sequence[InvariantResult],
    *,
    confidence_rank: int,
    min_confidence: int,
    confidence_label: str = "confidence",
) -> PromotionVerdict:
    """Decide whether a version may become authoritative.

    Invariants are checked first: a single deterministic failure rejects the
    version regardless of confidence (strong code is never overridden by a high
    score). Only when every invariant passes does confidence gate promotion.
    """
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
