"""Reporting-owned cash-flow response and proof DTOs."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.audit import JournalEntrySourceType
from src.ledger import JournalEntryAuthorityState


class CashFlowItem(BaseModel):
    """One classified cash-flow activity."""

    category: str
    subcategory: str
    amount: Decimal
    description: str | None = None
    account_id: UUID | None = Field(
        default=None,
        description="Account this line's movement belongs to, for report drill-down.",
    )


class CashFlowSummary(BaseModel):
    """Cash-flow statement totals."""

    operating_activities: Decimal
    investing_activities: Decimal
    financing_activities: Decimal
    net_cash_flow: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal


class CashFlowEventLineage(BaseModel):
    """Exact ledger and producer evidence for one cash event."""

    journal_entry_id: UUID
    journal_line_ids: list[UUID]
    source_type: JournalEntrySourceType
    source_id: UUID | None = None
    decision_anchor_id: UUID | None = None
    decision_authority_state: JournalEntryAuthorityState
    event_types: list[str] = Field(
        default_factory=list,
        description="Distinct journal-line event semantics evaluated by cash-flow classification.",
    )
    activity: Literal["Operating", "Investing", "Financing"] | None
    reason_code: str | None = None


class CashFlowBridge(BaseModel):
    """Exact reconciliation from classified events to the cash-balance delta."""

    classified_activity: Decimal
    unclassified_cash: Decimal
    fx_effect: Decimal
    cash_delta: Decimal
    reconciles: bool


class CashFlowResponse(BaseModel):
    """Cash-flow statement plus its machine-readable proof."""

    start_date: date
    end_date: date
    currency: str = Field(min_length=3, max_length=3, description="Cash-flow presentation currency.")
    operating: list[CashFlowItem]
    investing: list[CashFlowItem]
    financing: list[CashFlowItem]
    summary: CashFlowSummary
    fx_warnings: list[dict[str, str]] = Field(default_factory=list, description="Foreign-exchange conversion warnings.")
    cash_bridge: CashFlowBridge | None = Field(default=None, description="Cash-delta reconciliation proof.")
    event_lineage: list[CashFlowEventLineage] = Field(
        default_factory=list,
        description="Exact journal, producer, decision, and event-semantic evidence for cash movements.",
    )
    proof_state: Literal["proven", "unproven"]
    proof_reasons: list[str] = Field(
        description="Machine-readable reasons that prevent authoritative cash-flow output."
    )


__all__ = [
    "CashFlowBridge",
    "CashFlowEventLineage",
    "CashFlowItem",
    "CashFlowResponse",
    "CashFlowSummary",
]
