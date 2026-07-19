"""Reporting-owned envelope for exact package section contributions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar
from uuid import UUID

PackageContributionType = Literal["statement_source", "ledger_command", "valuation"]
PackageSectionId = Literal[
    "balance_sheet",
    "income_statement",
    "cash_flow",
    "investment_performance",
    "annualized_income_long_term",
    "traceability_appendix",
]
PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True, slots=True)
class PackageSectionContribution(Generic[PayloadT]):  # noqa: UP046 - mypy 1.11 lacks PEP 695 support.
    """Adapt one package-owned result without replacing its domain vocabulary.

    The payload remains the upstream package's typed contribution. This envelope
    standardizes only the information reporting needs to select sections and fold
    exact authority; it never derives authority from payload classifications.
    """

    contribution_type: PackageContributionType
    section_ids: tuple[PackageSectionId, ...]
    payload: PayloadT
    state: Literal["authoritative", "unproven"]
    decision_id: UUID | None
    input_refs: tuple[str, ...]
    reason_code: str | None

    def __post_init__(self) -> None:
        if not self.section_ids:
            raise ValueError("a package contribution requires at least one section")
        if not self.input_refs or any(not ref.strip() for ref in self.input_refs):
            raise ValueError("a package contribution requires exact input_refs")
        if self.state == "authoritative" and self.decision_id is None:
            raise ValueError("an authoritative package contribution requires a decision")
        if self.state == "unproven" and not self.reason_code:
            raise ValueError("an unproven package contribution requires a reason_code")

    @property
    def is_authoritative(self) -> bool:
        return self.state == "authoritative"
