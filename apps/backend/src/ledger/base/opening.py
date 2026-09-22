"""Evidence-bearing initial account stock, distinct from period activity."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from src.audit import TraceDecisionRef


@dataclass(frozen=True, slots=True)
class OpeningPosition:
    account_id: UUID
    effective_date: date
    amount: Decimal
    currency: str
    fx_rate: Decimal | None
    journal_entry_id: UUID | None
    decision: TraceDecisionRef | None
    state: str = "authoritative"
    reason_code: str | None = None
