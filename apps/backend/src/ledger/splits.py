"""Penny-rounding adjustment lines between a bank balance and a book balance.

``calculate_reconciliation_adjustment`` serves the reconciliation router (Flow 18). All
arithmetic is Decimal, quantized to 2 dp. The adjustment lines balance exactly: debits
equal credits.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.audit.money import to_money
from src.ledger.base.vocabulary import AccountType, Direction

__all__ = [
    "SplitLine",
    "ReconciliationAdjustment",
    "calculate_reconciliation_adjustment",
]

ZERO = Decimal("0")


def quantize_money(v: Decimal) -> Decimal:
    """Quantize to standard two decimal places using canonical banker's rounding."""
    return to_money(v)


class SplitLine(BaseModel):
    """One double-entry line in a composite split."""

    model_config = ConfigDict(frozen=True)

    role: str
    account_kind: AccountType
    direction: Direction
    amount: Decimal = Field(gt=ZERO)
    account_code: str | None = None

    @property
    def account_type(self) -> AccountType:
        return self.account_kind

    @field_validator("amount")
    @classmethod
    def _quantized(cls, v: Decimal) -> Decimal:
        return quantize_money(v)


def _assert_balanced(lines: Sequence[SplitLine]) -> None:
    if not lines:
        return
    if len(lines) < 2:
        raise ValueError(f"split must have at least 2 lines, got {len(lines)}")
    debits = ZERO
    credits = ZERO
    for item in lines:
        if item.amount <= ZERO:
            raise ValueError(f"split line amount must be > 0, got {item.amount}")
        if item.direction == Direction.DEBIT:
            debits += item.amount
        else:
            credits += item.amount
    if debits != credits:
        raise ValueError(f"split unbalanced: debit {debits} != credit {credits}")


class ReconciliationAdjustment(BaseModel):
    """Result of immaterial rounding / penny discrepancy write-off."""

    model_config = ConfigDict(frozen=True)

    bank_balance: Decimal
    book_balance: Decimal
    difference: Decimal
    is_gain: bool
    lines: tuple[SplitLine, ...]

    @model_validator(mode="after")
    def _invariants(self) -> ReconciliationAdjustment:
        _assert_balanced(self.lines)
        return self


def calculate_reconciliation_adjustment(
    bank_balance: Decimal,
    book_balance: Decimal,
    threshold: Decimal = Decimal("0.05"),
) -> ReconciliationAdjustment:
    """Calculate small penny rounding adjustment between bank and book balance."""
    bank = quantize_money(bank_balance)
    book = quantize_money(book_balance)
    diff = quantize_money(bank - book)

    if abs(diff) > quantize_money(threshold):
        raise ValueError(f"difference {diff} exceeds immaterial threshold {threshold}")

    is_gain = diff > ZERO
    abs_diff = abs(diff)

    if diff == ZERO:
        lines: tuple[SplitLine, ...] = ()
    elif is_gain:
        lines = (
            SplitLine(
                role="bank_adjustment",
                account_kind=AccountType.ASSET,
                direction=Direction.DEBIT,
                amount=abs_diff,
            ),
            SplitLine(
                role="rounding_income",
                account_kind=AccountType.INCOME,
                direction=Direction.CREDIT,
                amount=abs_diff,
            ),
        )
    else:
        lines = (
            SplitLine(
                role="rounding_expense",
                account_kind=AccountType.EXPENSE,
                direction=Direction.DEBIT,
                amount=abs_diff,
            ),
            SplitLine(
                role="bank_adjustment",
                account_kind=AccountType.ASSET,
                direction=Direction.CREDIT,
                amount=abs_diff,
            ),
        )

    return ReconciliationAdjustment(
        bank_balance=bank,
        book_balance=book,
        difference=diff,
        is_gain=is_gain,
        lines=lines,
    )
