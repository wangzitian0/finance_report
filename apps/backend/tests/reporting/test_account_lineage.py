"""Tests for account-lineage drill-down service (EPIC-022 AC22.3.3)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reporting import ReportError, get_account_lineage


@pytest.fixture
def user_id(test_user):
    return test_user.id


@pytest.fixture
async def cash_account(db: AsyncSession, user_id):
    account = Account(user_id=user_id, name="Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def test_AC22_3_3_account_lineage_returns_posted_contributing_lines(db: AsyncSession, user_id, cash_account):
    """AC-reporting.lineage.1: AC22.3.3: account-lineage returns posted journal lines with journal_line anchors and signed totals."""
    posted = JournalEntry(
        user_id=user_id, entry_date=date(2025, 1, 10), memo="Salary", status=JournalEntryStatus.POSTED
    )
    spend = JournalEntry(
        user_id=user_id, entry_date=date(2025, 1, 20), memo="Groceries", status=JournalEntryStatus.POSTED
    )
    draft = JournalEntry(user_id=user_id, entry_date=date(2025, 1, 25), memo="Draft", status=JournalEntryStatus.DRAFT)
    # Contra accounts so each entry has balanced debit/credit lines (>= 2 lines).
    income_acct = Account(user_id=user_id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    expense_acct = Account(user_id=user_id, name="Food", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([income_acct, expense_acct])
    db.add_all([posted, spend, draft])
    await db.flush()

    deposit_line = JournalLine(
        journal_entry_id=posted.id,
        account_id=cash_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    withdraw_line = JournalLine(
        journal_entry_id=spend.id,
        account_id=cash_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("250.00"),
        currency="SGD",
    )
    draft_line = JournalLine(
        journal_entry_id=draft.id,
        account_id=cash_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("999.00"),
        currency="SGD",
    )
    # Balancing contra lines (not on the cash account, so the assertions below
    # still see exactly the two posted cash lines).
    contra_lines = [
        JournalLine(
            journal_entry_id=posted.id,
            account_id=income_acct.id,
            direction=Direction.CREDIT,
            amount=Decimal("1000.00"),
            currency="SGD",
        ),
        JournalLine(
            journal_entry_id=spend.id,
            account_id=expense_acct.id,
            direction=Direction.DEBIT,
            amount=Decimal("250.00"),
            currency="SGD",
        ),
        JournalLine(
            journal_entry_id=draft.id,
            account_id=income_acct.id,
            direction=Direction.CREDIT,
            amount=Decimal("999.00"),
            currency="SGD",
        ),
    ]
    db.add_all([deposit_line, withdraw_line, draft_line, *contra_lines])
    await db.commit()

    result = await get_account_lineage(db, user_id, cash_account.id, as_of_date=date(2025, 1, 31), currency="SGD")

    assert result["account_id"] == cash_account.id
    assert result["account_name"] == "Checking"
    assert result["account_type"] == AccountType.ASSET
    assert result["currency"] == "SGD"

    # Draft line excluded; only the two posted lines contribute.
    line_ids = {line["journal_line_id"] for line in result["lines"]}
    assert line_ids == {deposit_line.id, withdraw_line.id}

    by_id = {line["journal_line_id"]: line for line in result["lines"]}
    # ASSET debit is positive, ASSET credit is negative.
    assert by_id[deposit_line.id]["amount"] == Decimal("1000.00")
    assert by_id[withdraw_line.id]["amount"] == Decimal("-250.00")
    # Each contributing line exposes its journal_entry anchor + memo for the UI.
    assert by_id[deposit_line.id]["journal_entry_id"] == posted.id
    assert by_id[deposit_line.id]["memo"] == "Salary"

    assert result["total"] == Decimal("750.00")


async def test_AC22_3_3_account_lineage_unknown_account_raises(db: AsyncSession, user_id, cash_account):
    """AC22.3.3: account-lineage rejects accounts the user does not own."""
    from uuid import uuid4

    with pytest.raises(ReportError):
        await get_account_lineage(db, user_id, uuid4(), as_of_date=date(2025, 1, 31))
