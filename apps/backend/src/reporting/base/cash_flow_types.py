"""Reporting-owned cash-flow response and proof DTOs."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.audit import JournalEntrySourceType
from src.ledger import JournalEntryAuthorityState

CurrencyStr = Annotated[str, Field(min_length=3, max_length=3)]
NonNegInt = Annotated[int, Field(ge=0)]
PosInt = Annotated[int, Field(ge=1)]
def _default_list() -> Any:
    return Field(default_factory=lambda: [])


class CashFlowItem(BaseModel):
    category: str
    subcategory: str
    amount: Decimal
    description: str | None = None
    account_id: UUID | None = None


class CashFlowSummary(BaseModel):
    operating_activities: Decimal
    investing_activities: Decimal
    financing_activities: Decimal
    net_cash_flow: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal


class CashFlowEventLineage(BaseModel):
    journal_entry_id: UUID
    journal_line_ids: list[UUID]
    source_type: JournalEntrySourceType
    source_id: UUID | None = None
    decision_anchor_id: UUID | None = None
    decision_authority_state: JournalEntryAuthorityState
    event_types: list[str] = _default_list()
    activity: Literal["Operating", "Investing", "Financing"] | None
    reason_code: str | None = None


class CashFlowBridge(BaseModel):
    classified_activity: Decimal
    unclassified_cash: Decimal
    fx_effect: Decimal
    opening_stock_adjustment: Decimal = Field(
        default=Decimal("0"), exclude_if=lambda value: value == 0, description="Initial stock adjustment."
    )
    cash_delta: Decimal
    discrepancy: Decimal = Decimal("0.00")
    reconciles: bool


class CashFlowResponse(BaseModel):
    start_date: date
    end_date: date
    currency: CurrencyStr
    operating: list[CashFlowItem]
    investing: list[CashFlowItem]
    financing: list[CashFlowItem]
    summary: CashFlowSummary
    fx_warnings: list[dict[str, str]] = _default_list()
    cash_bridge: CashFlowBridge | None = None
    event_lineage: list[CashFlowEventLineage] = _default_list()
    proof_state: Literal["proven", "unproven"]
    proof_reasons: list[str]


class CashFlowLine(CashFlowItem):
    line_id: str
    event_count: PosInt


class CashFlowLineageSummary(BaseModel):
    event_count: NonNegInt
    classified_event_count: NonNegInt
    unclassified_event_count: NonNegInt
    opening_stock_event_count: NonNegInt


class CashFlowPreview(BaseModel):
    model_config = {"extra": "forbid"}

    start_date: date
    end_date: date
    currency: CurrencyStr
    operating: list[CashFlowLine]
    investing: list[CashFlowLine]
    financing: list[CashFlowLine]
    summary: CashFlowSummary
    fx_warnings: list[dict[str, str]] = _default_list()
    cash_bridge: CashFlowBridge | None = None
    lineage_summary: CashFlowLineageSummary
    proof_state: Literal["proven", "unproven"]
    proof_reasons: list[str]


class CashFlowLineEvent(CashFlowEventLineage):
    entry_date: date
    memo: str
    amount: Decimal


class CashFlowLineEventsPage(BaseModel):
    line_id: str
    total: NonNegInt
    limit: PosInt
    offset: NonNegInt
    events: list[CashFlowLineEvent] = _default_list()


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
