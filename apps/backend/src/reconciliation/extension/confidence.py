from src.ledger import ConfidenceTier


def derive_reconciliation_score_tier(score: int | None) -> ConfidenceTier:
    """Map a reconciliation score to the Stage 2 review confidence tier."""
    if score is None:
        return "LOW"
    if score >= 85:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"
