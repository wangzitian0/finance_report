"""Pure summary read-model for Processing-account in-transit transfers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ProcessingTransferSummary:
    pending_count: int
    pending_total: Decimal
    current_balance: Decimal
    currency: str
    oldest_pending_date: date | None
