"""Tests for accounting balance aggregation helpers."""

from datetime import date
from decimal import Decimal

import pytest

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.services.accounting import calculate_account_balances


@pytest.mark.asyncio
async def test_calculate_account_balances_by_type(db, test_user) -> None:
    """Balances should aggregate by account with type-specific sign handling."""
    asset = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    expense = Account(user_id=test_user.id, name="Food", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([asset, income, expense])
    await db.commit()
    await db.refresh(asset)
    await db.refresh(income)
    await db.refresh(expense)

    entry_income = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Salary",
        status=JournalEntryStatus.POSTED,
    )
    entry_expense = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Lunch",
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([entry_income, entry_expense])
    await db.flush()

    lines = [
        JournalLine(
            journal_entry_id=entry_income.id,
            account_id=asset.id,
            direction=Direction.DEBIT,
            amount=Decimal("200.00"),
            currency="SGD",
        ),
        JournalLine(
            journal_entry_id=entry_income.id,
            account_id=income.id,
            direction=Direction.CREDIT,
            amount=Decimal("200.00"),
            currency="SGD",
        ),
        JournalLine(
            journal_entry_id=entry_expense.id,
            account_id=expense.id,
            direction=Direction.DEBIT,
            amount=Decimal("50.00"),
            currency="SGD",
        ),
        JournalLine(
            journal_entry_id=entry_expense.id,
            account_id=asset.id,
            direction=Direction.CREDIT,
            amount=Decimal("50.00"),
            currency="SGD",
        ),
    ]
    db.add_all(lines)
    await db.commit()

    balances = await calculate_account_balances(db, [asset, income, expense], test_user.id)

    assert balances[asset.id] == Decimal("150.00")
    assert balances[income.id] == Decimal("200.00")
    assert balances[expense.id] == Decimal("50.00")


@pytest.mark.asyncio
async def test_calculate_account_balances_empty_list(db, test_user) -> None:
    """Empty input should return an empty mapping."""
    balances = await calculate_account_balances(db, [], test_user.id)
    assert balances == {}
