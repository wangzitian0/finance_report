"""Constrained LLM valuation-classification output contract (#1224, EPIC-011 AC11.24).

The schema the model must fill to classify a raw valuation fact into the stable
taxonomy (``src.constants.valuation_taxonomy``). Binding the taxonomy fields to
the contract enums means the model cannot invent new report classes — an
out-of-contract code is a validation error, not a silently-accepted value. The
model adapts provider/jurisdiction/plan specifics (CPF, 401k, MPF, social
security, insurers) into these stable codes; the raw specifics are echoed back
as auditable metadata.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.constants.valuation_taxonomy import (
    EconomicSide,
    LiquidityClass,
    ValuationL1,
    ValuationL2,
    ValuationRole,
    parent_l1,
)


class ValuationEvidenceSpan(BaseModel):
    """A pointer back to where in the source a value was read."""

    page: int | None = None
    bbox: list[float] | None = None
    text: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ValuationClassificationLLMOutput(BaseModel):
    """The bounded output a model returns when classifying one valuation fact."""

    # Raw extracted values — echoed for auditability; jurisdiction/issuer/scheme
    # stay metadata and are never promoted into the stable codes.
    raw_label: str
    issuer: str | None = None
    jurisdiction: str | None = None
    scheme_name: str | None = None
    amount: Decimal
    currency: str
    as_of_date: date
    evidence_spans: list[ValuationEvidenceSpan] = Field(
        default_factory=list, description="Pointers back to where each value was read in the source."
    )

    # Stable classification — bound to the contract; out-of-contract values are
    # rejected by enum validation.
    l1: ValuationL1
    l2: ValuationL2 | None = None
    economic_side: EconomicSide
    valuation_role: ValuationRole
    liquidity_class: LiquidityClass
    confidence: Decimal
    rationale: str

    model_config = ConfigDict(from_attributes=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, value: Decimal) -> Decimal:
        if not (Decimal("0") <= value <= Decimal("1")):
            raise ValueError("confidence must be within [0, 1]")
        return value

    @model_validator(mode="after")
    def _stable_code_consistency(self) -> ValuationClassificationLLMOutput:
        # An L2 code must roll up to its declared L1 parent.
        if self.l2 is not None and parent_l1(self.l2) != self.l1:
            raise ValueError(f"l2 '{self.l2.value}' does not roll up to l1 '{self.l1.value}'")
        # A coverage amount is a non_asset (excluded from net worth); conversely
        # only a non_asset may carry the coverage_amount role.
        is_coverage = self.valuation_role == ValuationRole.COVERAGE_AMOUNT
        is_non_asset = self.economic_side == EconomicSide.NON_ASSET
        if is_coverage and not is_non_asset:
            raise ValueError("coverage_amount role requires economic_side=non_asset")
        if is_non_asset and self.valuation_role not in (
            ValuationRole.COVERAGE_AMOUNT,
            ValuationRole.INFORMATIONAL,
        ):
            raise ValueError("non_asset side must carry coverage_amount or informational role")
        return self
