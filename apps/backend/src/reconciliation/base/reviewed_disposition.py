"""Pure command shape for a human-reviewed source disposition."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.extraction import EconomicIntent


@dataclass(frozen=True, slots=True)
class ReviewedDispositionCommand:
    """Human-reviewed economic meaning required before a source entry is posted."""

    intent: EconomicIntent
    counter_account_id: UUID
    category: str | None
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.intent, EconomicIntent):
            raise TypeError("intent must be an EconomicIntent")
        if not self.rationale.strip():
            raise ValueError("Review rationale is required")
        if len(self.rationale) > 500:
            raise ValueError("Review rationale must be at most 500 characters")
        if self.category is not None and not self.category.strip():
            raise ValueError("Category cannot be blank")
