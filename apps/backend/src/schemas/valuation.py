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
    # stay metadata and are never promoted into the stable codes. Numeric and
    # currency bounds match the AtomicValuationFact storage constraints so the
    # contract rejects values that would later fail or be silently rounded.
    raw_label: str
    issuer: str | None = None
    jurisdiction: str | None = None
    scheme_name: str | None = None
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3, description="ISO-4217 code")
    as_of_date: date
    evidence_spans: list[ValuationEvidenceSpan] = Field(
        default_factory=list, description="Pointers back to where each value was read in the source."
    )

    # Stable classification — bound to the contract; out-of-contract values are
    # rejected by enum validation. confidence precision matches the
    # ValuationClassification Numeric(5,4) column.
    l1: ValuationL1
    l2: ValuationL2 | None = None
    economic_side: EconomicSide
    valuation_role: ValuationRole
    liquidity_class: LiquidityClass
    confidence: Decimal = Field(ge=0, le=1, max_digits=5, decimal_places=4)
    rationale: str

    # extra="forbid" keeps the bounded contract deterministic: prompt/model drift
    # that adds unknown keys fails loudly instead of being silently ignored.
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: object) -> object:
        # Normalize before the length constraint runs so " usd " -> "USD".
        return value.strip().upper() if isinstance(value, str) else value

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
