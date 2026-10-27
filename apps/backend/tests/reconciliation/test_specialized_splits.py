"""Flow 18 unit proofs: the adjustment lines behind AC-reconciliation.adjustment.1, and the SplitLine zero-plug rule."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.ledger import AccountType, Direction
from src.ledger.splits import SplitLine, calculate_reconciliation_adjustment


def test_flow_18_reconciliation_adjustment_loss():
    """Flow 18: Negative difference (bank < book) posts BankRoundingDifference expense."""
    result = calculate_reconciliation_adjustment(
        bank_balance=Decimal("1000.00"),
        book_balance=Decimal("1000.03"),
        threshold=Decimal("0.05"),
    )
    assert result.difference == Decimal("-0.03")
    assert result.is_gain is False
    assert len(result.lines) == 2

    exp_line = next(item for item in result.lines if item.role == "rounding_expense")
    assert exp_line.account_kind == AccountType.EXPENSE
    assert exp_line.direction == Direction.DEBIT
    assert exp_line.amount == Decimal("0.03")

    asset_line = next(item for item in result.lines if item.role == "bank_adjustment")
    assert asset_line.account_kind == AccountType.ASSET
    assert asset_line.direction == Direction.CREDIT
    assert asset_line.amount == Decimal("0.03")


def test_flow_18_reconciliation_adjustment_gain():
    """Flow 18: Positive difference (bank > book) posts RoundingGain income."""
    result = calculate_reconciliation_adjustment(
        bank_balance=Decimal("1000.02"),
        book_balance=Decimal("1000.00"),
        threshold=Decimal("0.05"),
    )
    assert result.difference == Decimal("0.02")
    assert result.is_gain is True
    assert len(result.lines) == 2

    asset_line = next(item for item in result.lines if item.role == "bank_adjustment")
    assert asset_line.account_kind == AccountType.ASSET
    assert asset_line.direction == Direction.DEBIT
    assert asset_line.amount == Decimal("0.02")

    gain_line = next(item for item in result.lines if item.role == "rounding_income")
    assert gain_line.account_kind == AccountType.INCOME
    assert gain_line.direction == Direction.CREDIT
    assert gain_line.amount == Decimal("0.02")


def test_flow_18_reconciliation_adjustment_threshold_exceeded():
    """Flow 18: Rejects differences exceeding immaterial threshold."""
    with pytest.raises(ValueError, match="exceeds immaterial threshold"):
        calculate_reconciliation_adjustment(
            bank_balance=Decimal("1000.00"),
            book_balance=Decimal("1000.10"),
            threshold=Decimal("0.05"),
        )


def test_split_line_rejects_zero_amount_plug():
    """Ensure SplitLine model strictly enforces positive amounts (anti-zero-plug invariant)."""
    with pytest.raises(ValidationError):
        SplitLine(
            role="zero_plug",
            account_kind=AccountType.ASSET,
            direction=Direction.DEBIT,
            amount=Decimal("0.00"),
        )
