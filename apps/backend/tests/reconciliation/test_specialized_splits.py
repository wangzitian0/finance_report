from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.ledger import AccountType, Direction
from src.ledger.splits import SplitLine, calculate_reconciliation_adjustment


@pytest.mark.parametrize(
    ("bank", "book", "diff", "is_gain", "roles"),
    [
        (
            "1000.00",
            "1000.03",
            "-0.03",
            False,
            {
                ("rounding_expense", AccountType.EXPENSE, Direction.DEBIT, "0.03"),
                ("bank_adjustment", AccountType.ASSET, Direction.CREDIT, "0.03"),
            },
        ),
        (
            "1000.02",
            "1000.00",
            "0.02",
            True,
            {
                ("bank_adjustment", AccountType.ASSET, Direction.DEBIT, "0.02"),
                ("rounding_income", AccountType.INCOME, Direction.CREDIT, "0.02"),
            },
        ),
    ],
)
def test_flow_18_reconciliation_adjustment_and_validation(
    bank: str, book: str, diff: str, is_gain: bool, roles: set[tuple]
) -> None:
    res = calculate_reconciliation_adjustment(
        bank_balance=Decimal(bank), book_balance=Decimal(book), threshold=Decimal("0.05")
    )
    assert res.difference == Decimal(diff) and res.is_gain is is_gain
    assert {(item.role, item.account_kind, item.direction, str(item.amount)) for item in res.lines} == roles


def test_flow_18_reconciliation_adjustment_threshold_and_zero_split() -> None:
    with pytest.raises(ValueError, match="exceeds immaterial threshold"):
        calculate_reconciliation_adjustment(
            bank_balance=Decimal("1000.00"), book_balance=Decimal("1000.10"), threshold=Decimal("0.05")
        )
    with pytest.raises(ValidationError):
        SplitLine(role="zero_plug", account_kind=AccountType.ASSET, direction=Direction.DEBIT, amount=Decimal("0.00"))
