"""Pure package-facing valuation contribution language (#1915)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from src.audit import TraceDecisionRef
from src.pricing.base.observation import ObservationSource
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject


@dataclass(frozen=True, slots=True)
class ResolvedValuationContribution:
    """The only valuation authority input a package consumer may freeze."""

    subject: PriceableSubject
    requested_as_of: date
    resolution_policy: str
    state: Literal["authoritative", "unproven"]
    reason_code: str | None
    lineage_id: str | None
    observation_id: UUID | None
    observation_version: str | None
    observation_as_of: date | None
    value: Decimal | None
    currency: str | None
    source: ObservationSource | None
    decision: TraceDecisionRef | None
    component_type: str | None = None
    valuation_basis: str | None = None
    liquidity_class: str | None = None

    def __post_init__(self) -> None:
        if self.state == "authoritative" and self.decision is None:
            raise ValueError("an authoritative valuation contribution requires a decision")
        if self.state == "authoritative" and self.reason_code is not None:
            raise ValueError("an authoritative valuation contribution cannot have a reason_code")
        if self.state == "unproven" and not self.reason_code:
            raise ValueError("an unproven valuation contribution requires a reason_code")
        if self.state == "unproven" and self.decision is not None:
            raise ValueError("an unproven valuation contribution cannot have a decision")

    @property
    def is_authoritative(self) -> bool:
        return self.state == "authoritative"

    @property
    def decision_id(self) -> UUID | None:
        return self.decision.decision_id if self.decision is not None else None

    @property
    def input_refs(self) -> tuple[str, ...]:
        if self.observation_id is None:
            return ()
        return (f"pricing_observation:{self.observation_id}",)


@dataclass(frozen=True, slots=True)
class MarketValuationSelection:
    """The exact market observation a report schedule rendered for one security."""

    subject: PriceableSubject
    observation_id: UUID
    requested_as_of: date


def resolution_policy_identity(policy: ResolutionPolicy) -> str:
    """Stable package-visible identity of one value-selection policy."""
    return f"max_age_days={policy.max_age_days};min_authority={policy.min_authority.name}"
