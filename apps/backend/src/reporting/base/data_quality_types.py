"""Data quality observatory domain value objects and response models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class QualityGrade(str, Enum):
    A_AUDIT_READY = "A_AUDIT_READY"
    B_BALANCED_GAPS = "B_BALANCED_GAPS"
    C_ATTENTION_NEEDED = "C_ATTENTION_NEEDED"
    D_OUT_OF_BALANCE = "D_OUT_OF_BALANCE"


class InvariantStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_healthy: bool
    name: str
    summary: str
    detail: str | None = None
    delta: Decimal | None = None


class MonthContinuityBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    month: str
    statement_count: int
    has_gap: bool
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    net_movement: Decimal | None = None
    status: Literal["HEALTHY", "GAP_DETECTED", "PENDING_PROCESSING", "NO_DATA"]


class QualityActionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    priority: Literal["P0", "P1", "P2"]
    title: str
    description: str
    score_boost: int
    action_type: Literal[
        "UPLOAD_STATEMENT",
        "REVIEW_STATEMENT",
        "RECONCILE_TRANSACTIONS",
        "RESOLVE_EQUATION",
        "RESOLVE_FX_RATE",
    ]
    action_url: str


class PersonalDataQualityHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: Annotated[int, Field(ge=0, le=100)]
    grade: QualityGrade
    as_of_date: date
    currency: str
    equation_invariant: InvariantStatus
    temporal_continuity_invariant: InvariantStatus
    reconciliation_purity_invariant: InvariantStatus
    lineage_anchors_invariant: InvariantStatus
    timeline: list[MonthContinuityBucket]
    action_items: list[QualityActionItem]
