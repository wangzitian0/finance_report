"""AC-reporting.package-annualized.3: Tests for income statement and annualized income default date adaptation."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine


async def test_annualized_income_adapts_to_latest_entry_date_when_as_of_omitted(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """When as_of is omitted, endpoint adapts to latest posted entry date instead of defaulting to today."""
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    db.add_all([salary, cash])
    await db.flush()

    historical_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2025, 4, 15),
        memo="historical salary",
        status=JournalEntryStatus.POSTED,
    )
    db.add(historical_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=historical_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("5000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=historical_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("5000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    response = await client.get("/income/annualized")
    assert response.status_code == 200
    data = response.json()
    assert data["as_of"] == "2025-04-15"
    assert data["annualized_salary"] == "5000.00"
    assert data["annualized_total"] == "5000.00"
