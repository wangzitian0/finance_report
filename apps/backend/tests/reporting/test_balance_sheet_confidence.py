"""Per-node confidence tier on balance-sheet payloads (EPIC-005 AC5.18, issue #913).

Axiom B: confidence is a first-class, measured property. Each balance-sheet line
carries the confidence tier of its contributing ledger facts, and an aggregate
(Net Worth) rolls up to the *worst-input* tier — a defined rollup, not an
invented number.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.reporting import generate_balance_sheet


async def _post(db, user_id, *, debit: Account, credit: Account, amount: Decimal, source_type) -> None:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 1, 15),
        memo="bs confidence",
        source_type=source_type,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id, account_id=debit.id, direction=Direction.DEBIT, amount=amount, currency="SGD"
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency="SGD",
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_AC5_18_1_lines_carry_worst_input_confidence_tier(db, test_user):
    """AC5.18.1: A line's tier is the worst confidence tier among its contributing entries."""
    cash = Account(user_id=test_user.id, name="Cash A", type=AccountType.ASSET, currency="SGD")
    savings = Account(user_id=test_user.id, name="Savings B", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, savings, salary])
    await db.flush()

    # Cash A built from a manual (TRUSTED) and an auto_parsed (LOW) entry -> worst is LOW.
    await _post(
        db, test_user.id, debit=cash, credit=salary, amount=Decimal("100.00"), source_type=JournalEntrySourceType.MANUAL
    )
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("50.00"),
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    # Savings B built only from a user_confirmed (HIGH) entry.
    await _post(
        db,
        test_user.id,
        debit=savings,
        credit=salary,
        amount=Decimal("200.00"),
        source_type=JournalEntrySourceType.USER_CONFIRMED,
    )

    report = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))

    lines = {line["name"]: line for line in report["assets"]}
    assert lines["Cash A"]["confidence_tier"] == "LOW"
    assert lines["Savings B"]["confidence_tier"] == "HIGH"


@pytest.mark.asyncio
async def test_AC5_18_2_net_worth_rolls_up_to_worst_input_tier(db, test_user):
    """AC5.18.2: The balance-sheet aggregate tier is the worst tier across its lines; None when there is nothing to rate."""
    empty = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert empty["confidence_tier"] is None
    assert empty["assets"] == []

    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    invest = Account(user_id=test_user.id, name="Brokerage", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, invest, salary])
    await db.flush()

    # One HIGH line and one LOW line -> aggregate is the worst (LOW).
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.USER_CONFIRMED,
    )
    await _post(
        db,
        test_user.id,
        debit=invest,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )

    report = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert report["confidence_tier"] == "LOW"
