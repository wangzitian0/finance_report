"""``src.audit.promotion`` — the deterministic promotion-gate submodule.

Keeps the published namespace while the package-owned value objects live in
``audit.base`` and the deterministic policy lives in ``audit.extension``.
Callers write
``from src.audit.promotion import evaluate_promotion`` or, for the
cross-package rule, ``from src.audit import evaluate_promotion`` (the
collision-free names are also re-exported flat at ``src.audit``'s root,
mirroring the ``money``/``quantity``/``ratio``/``unit_price`` pattern).
"""

from __future__ import annotations

from src.audit.base.promotion import (
    RECONCILIATION_AUTO_ACCEPT_SCORE,
    RECONCILIATION_REVIEW_SCORE,
    STATEMENT_BALANCE_TOLERANCE,
    InvariantResult,
    PromotionDecision,
    PromotionVerdict,
)
from src.audit.extension.promotion import evaluate_promotion, tier_rank

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
