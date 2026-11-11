"""Schemas for observable extraction feedback loops."""

from decimal import Decimal

from pydantic import BaseModel


class CorrectionLoopReplayResponse(BaseModel):
    holdout_size: int
    grounded: int
    proportion_before: Decimal
    proportion_after: Decimal
    reduced: bool
    high_confidence_count: int = 0
    medium_confidence_count: int = 0
    low_confidence_count: int = 0
    low_confidence_proportion: Decimal = Decimal("0")
