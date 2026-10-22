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
    opening_stock_adjustment: Decimal = Field(
        default=Decimal("0"),
        exclude_if=lambda value: value == 0,
        description="Initial stock first evidenced inside an incompletely covered period; never economic cash flow.",
    )
    cash_delta: Decimal
    discrepancy: Decimal = Decimal("0.00")
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


class CashFlowLine(CashFlowItem):
    """One statement line: the items of one activity, flow direction and counterpart (#2583)."""

    line_id: str = Field(description="Line id for GET /reports/cash-flow/line-events.")
    event_count: int = Field(ge=1, description="Number of cash events on this line.")


class CashFlowLineageSummary(BaseModel):
    """Counts of the lineage records of the complete cash-flow document (#2583).

    GET /reports/cash-flow/line-events returns the records page by page: a classified record
    under the line_id of its line, other records under "unclassified" and "opening_stock".
    """

    event_count: int = Field(ge=0, description="Number of lineage records.")
    classified_event_count: int = Field(ge=0, description="Records on an operating, investing or financing line.")
    unclassified_event_count: int = Field(ge=0, description='Records under the line_id "unclassified".')
    opening_stock_event_count: int = Field(ge=0, description='Records under the line_id "opening_stock".')


class CashFlowPreview(BaseModel):
    """Bounded projection of one cash-flow document (#2583).

    Each section has one line for each activity, flow direction and counterpart, with its event
    count. The lineage records load page by page from GET /reports/cash-flow/line-events. The
    CSV export and a package snapshot keep the complete document.
    """

    model_config = {"extra": "forbid"}

    start_date: date
    end_date: date
    currency: str = Field(min_length=3, max_length=3, description="Cash-flow presentation currency.")
    operating: list[CashFlowLine]
    investing: list[CashFlowLine]
    financing: list[CashFlowLine]
    summary: CashFlowSummary
    fx_warnings: list[dict[str, str]] = Field(default_factory=list, description="Foreign-exchange conversion warnings.")
    cash_bridge: CashFlowBridge | None = Field(default=None, description="Cash-delta reconciliation proof.")
    lineage_summary: CashFlowLineageSummary
    proof_state: Literal["proven", "unproven"]
    proof_reasons: list[str] = Field(
        description="Machine-readable reasons that prevent authoritative cash-flow output."
    )


class CashFlowLineEvent(CashFlowEventLineage):
    """One lineage record of a cash-flow line, with its journal entry and amount (#2583)."""

    entry_date: date
    memo: str
    amount: Decimal = Field(description="Cash movement of this record in the presentation currency.")


class CashFlowLineEventsPage(BaseModel):
    """One page of the lineage records of one cash-flow line, in document order (#2583)."""

    line_id: str
    total: int = Field(ge=0, description="Number of records on this line.")
    limit: int = Field(ge=1, description="Maximum number of records in this page.")
    offset: int = Field(ge=0, description="Number of records before this page.")
    events: list[CashFlowLineEvent] = Field(default_factory=list, description="Records of this page.")


__all__ = [
    "CashFlowBridge",
    "CashFlowEventLineage",
    "CashFlowItem",
    "CashFlowLine",
    "CashFlowLineEvent",
    "CashFlowLineEventsPage",
    "CashFlowLineageSummary",
    "CashFlowPreview",
    "CashFlowResponse",
    "CashFlowSummary",
]
