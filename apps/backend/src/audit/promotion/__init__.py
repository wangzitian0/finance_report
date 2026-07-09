"""``src.audit.promotion`` — the deterministic promotion-gate submodule.

Re-exports :mod:`src.audit.promotion.gate`'s public surface (moved from
``src.services.promotion_gate``, #1667) so callers write
``from src.audit.promotion import evaluate_promotion`` or, for the
cross-package rule, ``from src.audit import evaluate_promotion`` (the
collision-free names are also re-exported flat at ``src.audit``'s root,
mirroring the ``money``/``quantity``/``ratio``/``unit_price`` pattern).
"""

from __future__ import annotations

from src.audit.promotion.gate import (
    RECONCILIATION_AUTO_ACCEPT_SCORE,
    RECONCILIATION_REVIEW_SCORE,
    STATEMENT_BALANCE_TOLERANCE,
    InvariantResult,
    PromotionDecision,
    PromotionVerdict,
    evaluate_promotion,
    tier_rank,
)

__all__ = [
    "RECONCILIATION_AUTO_ACCEPT_SCORE",
    "RECONCILIATION_REVIEW_SCORE",
    "STATEMENT_BALANCE_TOLERANCE",
    "InvariantResult",
    "PromotionDecision",
    "PromotionVerdict",
    "evaluate_promotion",
    "tier_rank",
]
