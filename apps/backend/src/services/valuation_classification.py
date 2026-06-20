"""Valuation classification review gating + persistence mapping (#1224, AC11.24).

Turns a validated ``ValuationClassificationLLMOutput`` into a gated result: a
low-confidence or ambiguous classification enters review (``PENDING``) instead of
being trusted for reports, while a confident one is auto-approved. The prompt and
model identifiers are carried through so they are persisted with the
classification. No live LLM call is made here — this is the deterministic
contract + gate that wraps whatever transport produces the output.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from src.constants.valuation_taxonomy import EconomicSide
from src.models.valuation import ValuationReviewStatus
from src.schemas.valuation import ValuationClassificationLLMOutput

# Versioned so every persisted classification records what produced it.
VALUATION_CLASSIFICATION_PROMPT_VERSION = "valuation-classify-v1"

# At or above this confidence a classification is trusted for report use; below
# it the classification is routed to review. Mirrors the extraction confidence
# gate, expressed on the 0..1 scale.
REVIEW_CONFIDENCE_THRESHOLD = Decimal("0.85")


@dataclass(frozen=True)
class GatedValuationClassification:
    """An LLM classification plus its review decision and provenance versions."""

    output: ValuationClassificationLLMOutput
    review_status: ValuationReviewStatus
    model_version: str
    prompt_version: str

    @property
    def contributes_to_net_worth(self) -> bool:
        """Non-asset valuations (e.g. insurance coverage) never enter net worth."""

        return self.output.economic_side != EconomicSide.NON_ASSET

    @property
    def is_trusted_for_reports(self) -> bool:
        return self.review_status == ValuationReviewStatus.APPROVED


def gate_classification(
    output: ValuationClassificationLLMOutput,
    *,
    model_version: str,
    prompt_version: str = VALUATION_CLASSIFICATION_PROMPT_VERSION,
) -> GatedValuationClassification:
    """Route a validated classification to review or trusted use by confidence."""

    review_status = (
        ValuationReviewStatus.APPROVED
        if output.confidence >= REVIEW_CONFIDENCE_THRESHOLD
        else ValuationReviewStatus.PENDING
    )
    return GatedValuationClassification(
        output=output,
        review_status=review_status,
        model_version=model_version,
        prompt_version=prompt_version,
    )


def build_classification_fields(
    *,
    valuation_fact_id: UUID,
    user_id: UUID,
    gated: GatedValuationClassification,
) -> dict:
    """Persistence kwargs for a ``ValuationClassification`` row.

    Carries the stable codes, confidence, review status, and — per AC11.24 — the
    prompt and model versions that produced the classification.
    """

    o = gated.output
    return {
        "valuation_fact_id": valuation_fact_id,
        "user_id": user_id,
        "l1": o.l1,
        "l2": o.l2,
        "economic_side": o.economic_side,
        "valuation_role": o.valuation_role,
        "liquidity_class": o.liquidity_class,
        "confidence": o.confidence,
        "review_status": gated.review_status,
        "model_version": gated.model_version,
        "prompt_version": gated.prompt_version,
        "rationale": o.rationale,
    }
