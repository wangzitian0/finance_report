"""Pure statement-source contribution language for package consumers (#1681)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from src.audit import TraceDecisionRef
from src.extraction.base.result import StatementExtractionResult


@dataclass(frozen=True, slots=True)
class ResolvedStatementContribution:
    """One current immutable source result and its exact authority decision.

    Consumers may render or freeze ``source_result`` but may not use its
    provenance, confidence, source type, or timestamps as an authority signal.
    ``state`` is determined solely by the current target-matching TraceRecord
    decision resolved by extraction's extension boundary.
    """

    statement_id: UUID
    source_result_id: UUID | None
    source_result: StatementExtractionResult | None
    effective_period_start: date | None
    effective_period_end: date | None
    state: Literal["authoritative", "unproven"]
    reason_code: str | None
    decision: TraceDecisionRef | None
    source_document_id: UUID | None = None
    account_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.state == "authoritative" and (
            self.source_result_id is None
            or self.source_result is None
            or self.decision is None
            or self.effective_period_start is None
            or self.effective_period_end is None
        ):
            raise ValueError("an authoritative statement contribution requires source identity and decision")
        if self.state == "authoritative" and self.reason_code is not None:
            raise ValueError("an authoritative statement contribution cannot have a reason_code")
        if (
            self.effective_period_start is not None
            and self.effective_period_end is not None
            and self.effective_period_start > self.effective_period_end
        ):
            raise ValueError("effective statement period is invalid")
        if self.state == "unproven" and not self.reason_code:
            raise ValueError("an unproven statement contribution requires a reason_code")
        if self.state == "unproven" and self.decision is not None:
            raise ValueError("an unproven statement contribution cannot have a decision")

    @property
    def is_authoritative(self) -> bool:
        return self.state == "authoritative"

    @property
    def decision_id(self) -> UUID | None:
        return self.decision.decision_id if self.decision is not None else None

    @property
    def input_refs(self) -> tuple[str, ...]:
        if self.source_result_id is None:
            return ()
        refs = [f"statement_result:{self.source_result_id}"]
        if self.source_document_id is not None:
            refs.append(f"source_document:{self.source_document_id}")
        if self.account_id is not None:
            refs.append(f"account:{self.account_id}")
        return tuple(refs)
