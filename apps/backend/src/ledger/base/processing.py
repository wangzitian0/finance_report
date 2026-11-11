"""Pure Processing virtual-account core (`code="1199"`) and transfer-pair scoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Generic, TypeVar
from uuid import UUID

from src.ledger.base.validators import ValidationError
from src.ledger.base.vocabulary import AccountType, Direction

PROCESSING_ACCOUNT_CODE = "1199"
PROCESSING_ACCOUNT_NAME = "Processing"
PROCESSING_ACCOUNT_TYPE = AccountType.ASSET
PROCESSING_ACCOUNT_DESCRIPTION = "System-managed virtual account for tracking in-transit transfers"

TRANSFER_KEYWORDS = ["transfer", "payment to", "fund transfer", "withdrawal", "paynow", "fast", "giro"]

AUTO_PAIR_THRESHOLD = 85
AMOUNT_WEIGHT = Decimal("0.40")
DESCRIPTION_WEIGHT = Decimal("0.30")
DATE_WEIGHT = Decimal("0.20")
HISTORY_WEIGHT = Decimal("0.10")
MAX_DATE_DIFF_DAYS = 7


class ProcessingCurrencyConflictError(ValidationError):
    """Persisted Processing account conflicts with the effective base currency."""


class TransferAccountCurrencyMismatchError(ValidationError):
    """Transfer leg cannot use the non-FX Processing posting path."""


@dataclass(frozen=True)
class ProcessingAccount:
    """Fixed identity of the per-user Processing virtual account."""

    code: str = PROCESSING_ACCOUNT_CODE
    name: str = PROCESSING_ACCOUNT_NAME
    type: AccountType = PROCESSING_ACCOUNT_TYPE
    description: str = PROCESSING_ACCOUNT_DESCRIPTION
    is_system: bool = True


EntryT = TypeVar("EntryT")


@dataclass
class TransferPair(Generic[EntryT]):  # noqa: UP046
    """Matched pair of transfer entries."""

    out_entry: EntryT
    in_entry: EntryT
    confidence: int
    score_breakdown: dict[str, float]


def _validate_transfer_params(amount: Decimal, description: str) -> None:
    if amount <= Decimal("0"):
        raise ValueError("Transfer amount must be positive")
    if not description or not description.strip():
        raise ValueError("Transfer description must not be empty")


def detect_transfer_pattern(description: str | None) -> bool:
    if not description:
        return False
    lower = description.lower()
    return any(kw in lower for kw in TRANSFER_KEYWORDS)


def _score_amount_match(amount1: Decimal, amount2: Decimal) -> float:
    diff = abs(amount1 - amount2)
    for limit, score in (
        (Decimal("0.01"), 100.0),
        (Decimal("0.10"), 95.0),
        (Decimal("1.00"), 85.0),
        (Decimal("5.00"), 70.0),
    ):
        if diff <= limit:
            return score
    if amount1 == Decimal("0"):
        return 0.0
    return float(round(max(Decimal("0"), Decimal("100") - (diff / amount1) * Decimal("100")), 2))


def _score_date_proximity(date1: date, date2: date) -> float:
    diff_days = abs((date1 - date2).days)
    for limit, score in ((0, 100.0), (1, 95.0), (3, 85.0), (MAX_DATE_DIFF_DAYS, 70.0)):
        if diff_days <= limit:
            return score
    return float(max(0, 100 - diff_days * 10))


def _calculate_pair_confidence(
    out_entry: Any,
    in_entry: Any,
    processing_account_id: UUID | None = None,
    *,
    description_scorer: Callable[[str | None, str | None], float],
) -> tuple[int, dict[str, float]]:
    if processing_account_id is None:
        processing_account_id = next(
            (line.account_id for line in out_entry.lines if line.direction == Direction.DEBIT), None
        )
    out_amount = next(
        (line.amount for line in out_entry.lines if line.account_id == processing_account_id and line.direction == Direction.DEBIT),
        Decimal("0"),
    )
    in_amount = next(
        (line.amount for line in in_entry.lines if line.account_id == processing_account_id and line.direction == Direction.CREDIT),
        Decimal("0"),
    )
    breakdown = {
        "amount": _score_amount_match(out_amount, in_amount),
        "description": description_scorer(out_entry.memo, in_entry.memo),
        "date": _score_date_proximity(out_entry.entry_date, in_entry.entry_date),
        "history": 0.0,
    }
    total = sum(
        (
            Decimal(str(breakdown[k])) * w
            for k, w in (
                ("amount", AMOUNT_WEIGHT),
                ("description", DESCRIPTION_WEIGHT),
                ("date", DATE_WEIGHT),
                ("history", HISTORY_WEIGHT),
            )
        ),
        Decimal("0"),
    )
    return int(round(total, 0)), breakdown
