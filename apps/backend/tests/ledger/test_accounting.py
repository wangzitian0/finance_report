from decimal import Decimal
from uuid import uuid4
import pytest
from src.ledger import Direction, JournalLine, ValidationError, validate_fx_rates, validate_journal_balance


async def test_balanced_entry_passes():
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        ),
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("100.00"),
            currency="SGD",
        ),
    ]
    validate_journal_balance(lines)
    total_debit = sum((line.amount for line in lines if line.direction == Direction.DEBIT), Decimal("0"))
    total_credit = sum((line.amount for line in lines if line.direction == Direction.CREDIT), Decimal("0"))
    imbalance = abs(total_debit - total_credit)
    assert imbalance == Decimal("0")


async def test_unbalanced_entry_fails():
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        ),
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("90.00"),
            currency="SGD",
        ),
    ]
    with pytest.raises(ValidationError, match="not balanced"):
        validate_journal_balance(lines)


async def test_single_line_entry_fails():
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        )
    ]
    with pytest.raises(ValidationError, match="at least 2 lines"):
        validate_journal_balance(lines)


async def test_decimal_precision():
    amount1 = Decimal("100.50")
    amount2 = Decimal("50.25")
    total = amount1 + amount2
    assert total == Decimal("150.75")
    assert str(total) == "150.75"


async def test_fx_rate_required_for_non_base_currency():
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="USD",
            fx_rate=None,
        )
    ]
    with pytest.raises(ValidationError, match="fx_rate required"):
        validate_fx_rates(lines)
    _m1_lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency=None,
            fx_rate=None,
        )
    ]
    validate_fx_rates(_m1_lines)


async def test_missing_currency_balances_as_base_currency():
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency=None,
            fx_rate=None,
        ),
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("100.00"),
            currency=None,
            fx_rate=None,
        ),
    ]
    validate_journal_balance(lines)
    _m2_lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="USD",
            fx_rate=None,
        ),
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("100.00"),
            currency="SGD",
            fx_rate=None,
        ),
    ]
    with pytest.raises(ValidationError, match="fx_rate required for currency USD"):
        validate_journal_balance(_m2_lines)
