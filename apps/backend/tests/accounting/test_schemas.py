from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.audit import JournalEntrySourceType
from src.ledger import AccountType, Direction
from src.portfolio import InvestmentAccountingService, InvestmentAccountingValidationError
from src.reporting.extension.reporting_calc import _provenance_from_source_type, _quantize_money, income_bucket
from src.schemas import AccountCreate, AccountUpdate, JournalEntryCreate, JournalLineCreate, VoidJournalEntryRequest


def test_account_and_void_schemas() -> None:
    full = AccountCreate(name="Full", code="1100", type=AccountType.LIABILITY, currency="USD", description="Desc")
    assert (full.code, full.description, full.currency) == ("1100", "Desc", "USD")
    upd = AccountUpdate(name="New Name")
    assert (upd.name, upd.code, upd.is_active) == ("New Name", None, None)
    assert VoidJournalEntryRequest(reason="Void reason").reason == "Void reason"
    for bad in (
        lambda: AccountCreate(name="", type=AccountType.ASSET, currency="SGD"),
        lambda: AccountCreate(name="Test", type=AccountType.ASSET, currency="SGDX"),
        lambda: VoidJournalEntryRequest(reason=""),
    ):
        with pytest.raises(ValidationError):
            bad()


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("123.45", Decimal("123.45")), ("1.50E+2", Decimal("150.00")), (Decimal("100.50"), Decimal("100.50"))],
)
def test_journal_line_decimal_parsing(amount, expected) -> None:
    line = JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=amount, currency="SGD")
    assert line.amount == expected and isinstance(line.amount, Decimal)


def test_journal_line_and_entry_schemas() -> None:
    try:
        obj = JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=0.1 + 0.2, currency="SGD")
    except Exception:
        pass
    else:
        assert obj.amount == Decimal("0.30")
    for bad_amt in (Decimal("0"), Decimal("-10.00")):
        with pytest.raises(ValidationError):
            JournalLineCreate(account_id=uuid4(), direction=Direction.CREDIT, amount=bad_amt, currency="SGD")

    fx_entry = JournalEntryCreate(
        entry_date=date(2026, 1, 1),
        memo="SGD<->USD",
        lines=[
            JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=Decimal("135.00"), currency="SGD"),
            JournalLineCreate(
                account_id=uuid4(),
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
                fx_rate=Decimal("1.350000"),
            ),
        ],
    )
    assert fx_entry.lines[1].fx_rate == Decimal("1.350000")
    for bad_lines in (
        [JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=Decimal("100.00"), currency="SGD")],
        [],
    ):
        with pytest.raises(ValidationError):
            JournalEntryCreate(entry_date=date.today(), memo="Invalid", lines=bad_lines)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Monthly Salary", "salary"),
        ("Annual Bonus", "bonus"),
        ("Dividend payout", "dividend"),
        ("grocery refund", None),
    ],
)
def test_income_bucket_and_quantize_money(text, expected) -> None:
    assert income_bucket(text) == expected
    assert _quantize_money(5) == Decimal("5.00")
    assert _quantize_money(Decimal("1.005")) == Decimal("1.00")


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        (JournalEntrySourceType.MANUAL, "manual"),
        ("bank_statement", "imported"),
        (JournalEntrySourceType.SYSTEM, "derived"),
        (JournalEntrySourceType.FX_REVALUATION, "derived"),
        ("manual", "manual"),
        (None, None),
        ("not-a-valid-source", None),
    ],
)
def test_provenance_from_source_type(source_type, expected) -> None:
    assert _provenance_from_source_type(source_type) == expected


def test_investment_validation_helpers() -> None:
    service = InvestmentAccountingService()
    service._validate_positive(Decimal("1"), "quantity")
    service._validate_non_negative(Decimal("0"), "fees")
    with pytest.raises(InvestmentAccountingValidationError, match="must be positive"):
        service._validate_positive(Decimal("0"), "quantity")
    with pytest.raises(InvestmentAccountingValidationError, match="cannot be negative"):
        service._validate_non_negative(Decimal("-1"), "fees")
