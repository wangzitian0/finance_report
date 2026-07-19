"""Schemas for observable extraction feedback loops."""

from decimal import Decimal

from pydantic import BaseModel


class CorrectionLoopReplayResponse(BaseModel):
    """The held-out replay of the live correction corpus (EPIC-018 AC18.14).

    The furnace made observable: how much the recurring-correction priors lower the
    held-out low-confidence proportion. `reduced` is the auditable yes/no of whether
    the loop measurably improved the proportion over this corpus.
    """

    holdout_size: int
    grounded: int
    proportion_before: Decimal
    proportion_after: Decimal
    reduced: bool
