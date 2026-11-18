from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType, JournalEntryStatus
from src.reporting import ReportError, get_account_lineage
from tests.reporting._report_fixtures import post_pair, seed_accounts


async def test_AC22_3_3_account_lineage_returns_posted_contributing_lines(db: AsyncSession, test_user) -> None:
    cash, income, expense = await seed_accounts(
        db,
        test_user.id,
        ("Checking", AccountType.ASSET),
        ("Salary Income", AccountType.INCOME),
        ("Food", AccountType.EXPENSE),
    )
    posted = await post_pair(db, test_user.id, date(2025, 1, 10), "Salary", cash, income, "1000.00")
    await post_pair(db, test_user.id, date(2025, 1, 20), "Groceries", expense, cash, "250.00")
    await post_pair(
        db,
        test_user.id,
        date(2025, 1, 25),
        "Draft",
        cash,
        income,
        "999.00",
        status=JournalEntryStatus.DRAFT,
        commit=True,
    )

    res = await get_account_lineage(db, test_user.id, cash.id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert (res["account_id"], res["account_name"], res["account_type"], res["currency"], res["total"]) == (
        cash.id,
        "Checking",
        AccountType.ASSET,
        "SGD",
        Decimal("750.00"),
    )
    by_memo = {line["memo"]: line for line in res["lines"]}
    assert set(by_memo) == {"Salary", "Groceries"}
    assert (by_memo["Salary"]["amount"], by_memo["Salary"]["journal_entry_id"], by_memo["Groceries"]["amount"]) == (
        Decimal("1000.00"),
        posted.id,
        Decimal("-250.00"),
    )

    with pytest.raises(ReportError):
        await get_account_lineage(db, test_user.id, uuid4(), as_of_date=date(2025, 1, 31))
