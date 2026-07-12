"""Confidence tier derivation.

``ConfidenceTier`` and ``derive_confidence_tier`` now live in the model layer
(:mod:`src.ledger.orm.journal`, co-located with the ``source_type`` column they
map) so the model no longer imports a service — the previous ``model → service``
import cycle is removed. They are re-exported here for the existing call sites.

``derive_reconciliation_score_tier`` stays here: it maps a numeric score (not a
journal enum) and has no model dependency.
"""

from src.ledger import ConfidenceTier, derive_confidence_tier

__all__ = [
    "ConfidenceTier",
    "derive_confidence_tier",
    "derive_reconciliation_score_tier",
]


def derive_reconciliation_score_tier(score: int | None) -> ConfidenceTier:
    """Map a reconciliation score to the Stage 2 review confidence tier."""
    if score is None:
        return "LOW"
    if score >= 85:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"
