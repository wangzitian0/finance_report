"""Pure value language consumed and produced by the promotion policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

STATEMENT_BALANCE_TOLERANCE = Decimal("0.001")
RECONCILIATION_AUTO_ACCEPT_SCORE = 85
RECONCILIATION_REVIEW_SCORE = 60


class PromotionDecision(StrEnum):
    AUTHORITATIVE = "authoritative"
    REVIEW = "review"
    REJECTED = "rejected"


@dataclass(frozen=True)
class InvariantResult:
    name: str
    passed: bool
    delta: Decimal | None = None
    tolerance: Decimal | None = None


@dataclass(frozen=True)
class PromotionVerdict:
    decision: PromotionDecision
    invariants_pass: bool
    confidence_ok: bool
    reason: str
    failed_invariant: str | None = None
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def is_authoritative(self) -> bool:
        return self.decision is PromotionDecision.AUTHORITATIVE
