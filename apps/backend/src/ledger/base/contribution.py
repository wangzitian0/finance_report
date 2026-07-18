"""Pure journal contribution values published to package consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from src.ledger.orm.account import AccountType
from src.ledger.orm.journal import Direction


@dataclass(frozen=True, slots=True)
class JournalLineContribution:
    line_id: UUID
    account_id: UUID
    account_type: AccountType
    direction: Direction
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ResolvedJournalContribution:
    entry_id: UUID
    entry_date: date
    lines: tuple[JournalLineContribution, ...]
    state: Literal["authoritative", "unproven"]
    reason_code: str | None
    decision_id: UUID | None

    def __post_init__(self) -> None:
        if self.state == "authoritative" and self.decision_id is None:
            raise ValueError("an authoritative journal contribution requires a decision")
        if self.state == "unproven" and not self.reason_code:
            raise ValueError("an unproven journal contribution requires a reason_code")

    @property
    def is_authoritative(self) -> bool:
        return self.state == "authoritative"

    @property
    def input_refs(self) -> tuple[str, ...]:
        return (f"journal_entry:{self.entry_id}", *(f"journal_line:{line.line_id}" for line in self.lines))
