"""Data quality observatory domain value objects and response models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QualityGrade(str, Enum):
    """Overall data quality grade."""

    A_AUDIT_READY = "A_AUDIT_READY"
    B_BALANCED_GAPS = "B_BALANCED_GAPS"
    C_ATTENTION_NEEDED = "C_ATTENTION_NEEDED"
    D_OUT_OF_BALANCE = "D_OUT_OF_BALANCE"


class InvariantStatus(BaseModel):
    """Invariant status and audit proof details."""

    model_config = ConfigDict(frozen=True)

    is_healthy: bool = Field(description="Whether the invariant is strictly satisfied.")
    name: str = Field(description="Human-readable invariant name.")
    summary: str = Field(description="Short summary statement of verification status.")
    detail: str | None = Field(default=None, description="Detailed explanation or root-cause guidance.")
    delta: Decimal | None = Field(default=None, description="Numeric variance or discrepancy delta if applicable.")


class MonthContinuityBucket(BaseModel):
    """Monthly continuity bucket across the temporal timeline."""

    model_config = ConfigDict(frozen=True)

    month: str = Field(description="Year and month identifier formatted as YYYY-MM.")
    statement_count: int = Field(description="Number of uploaded statements covering this monthly period.")
    has_gap: bool = Field(description="Whether a missing period gap was detected for this month.")
    opening_balance: Decimal | None = Field(
        default=None, description="Opening balance recorded at the start of the period."
    )
    closing_balance: Decimal | None = Field(
        default=None, description="Closing balance recorded at the end of the period."
    )
    net_movement: Decimal | None = Field(
        default=None, description="Calculated net movement (closing minus opening balance)."
    )
    status: Literal["HEALTHY", "GAP_DETECTED", "PENDING_PROCESSING", "NO_DATA"] = Field(
        description="Continuity status category for this monthly period."
    )


class QualityActionItem(BaseModel):
    """Actionable improvement item to boost data quality."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Unique identifier for the action item.")
    priority: Literal["P0", "P1", "P2"] = Field(description="Urgency priority ranking for the remedial action.")
    title: str = Field(description="Concise, action-oriented title.")
    description: str = Field(description="Specific instructions detailing how to complete the action.")
    score_boost: int = Field(description="Estimated points increase upon completing this action.")
    action_type: Literal[
        "UPLOAD_STATEMENT",
        "REVIEW_STATEMENT",
        "RECONCILE_TRANSACTIONS",
        "RESOLVE_EQUATION",
    ] = Field(description="Categorical action type triggering workflow navigation.")
    action_url: str = Field(description="Relative application URL to navigate and resolve the item.")


class PersonalDataQualityHealthResponse(BaseModel):
    """Response payload for the personal data quality observatory."""

    model_config = ConfigDict(frozen=True)

    score: int = Field(
        ge=0,
        le=100,
        description="Overall financial data quality trust score from 0 to 100.",
    )
    grade: QualityGrade = Field(description="Overall quality grade classification from A to D.")
    as_of_date: date = Field(description="Effective valuation date for the invariant calculations.")
    currency: str = Field(description="Three-letter ISO currency code used for reporting figures.")

    # 4 Core Invariants
    equation_invariant: InvariantStatus = Field(
        description="Accounting equation balance invariant proof (Assets = Liabilities + Equity)."
    )
    temporal_continuity_invariant: InvariantStatus = Field(
        description="Multi-period cash rollforward and statement continuity invariant proof."
    )
    reconciliation_purity_invariant: InvariantStatus = Field(
        description="Debt settlement purity and transaction reconciliation completeness proof."
    )
    lineage_anchors_invariant: InvariantStatus = Field(
        description="Source document lineage and evidence graph anchor coverage proof."
    )

    # 12-Month Temporal Timeline
    timeline: list[MonthContinuityBucket] = Field(
        description="12-month rolling statement continuity and cash movement timeline."
    )

    # Prioritized Action Items
    action_items: list[QualityActionItem] = Field(description="Prioritized remediation items ranked by score impact.")
