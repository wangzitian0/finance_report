"""Year-scale reporting validation (#951, EPIC-005 AC5.20).

A single user's full year of activity is low-thousands of journal lines. This
gates (in the default CI lane) that the balance sheet, income statement, and
cash flow still produce correct, tied-out numbers at that volume — guarding the
income-statement Python-side aggregation against a silent O(n^2) regression — and
keeps generation under a generous wall-clock backstop.
"""

import time
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement

ENTRY_COUNT = 1000
AMOUNT = Decimal("100.00")
LATENCY_BUDGET_SECONDS = 30.0  # generous regression backstop, not a benchmark


async def test_AC5_20_year_scale_reporting_ties_out_within_budget(db: AsyncSession, test_user) -> None:
    """AC-reporting.year-scale.1: AC5.20.1: at a full year's transaction volume the three core statements
    tie out and generate within a generous wall-clock budget."""
    user_id = test_user.id
    bank = Account(user_id=user_id, name="Bank", code="1001", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", code="4001", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, salary])
    await db.flush()

    start = date(2026, 1, 1)
    entries = []
    for i in range(ENTRY_COUNT):
        entry = JournalEntry(
            user_id=user_id,
            entry_date=start + timedelta(days=i % 365),
            memo=f"txn {i}",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        entry.lines = [
            JournalLine(account_id=bank.id, direction=Direction.DEBIT, amount=AMOUNT, currency="SGD"),
            JournalLine(account_id=salary.id, direction=Direction.CREDIT, amount=AMOUNT, currency="SGD"),
        ]
        entries.append(entry)
    db.add_all(entries)
    await db.commit()

    period_start = date(2026, 1, 1)
    period_end = date(2026, 12, 31)
    started = time.perf_counter()
    balance_sheet = await generate_balance_sheet(db, user_id, as_of_date=period_end, currency="SGD")
    income_statement = await generate_income_statement(
        db, user_id, start_date=period_start, end_date=period_end, currency="SGD"
    )
    cash_flow = await generate_cash_flow(db, user_id, start_date=period_start, end_date=period_end, currency="SGD")
    elapsed = time.perf_counter() - started

    expected_total = AMOUNT * ENTRY_COUNT  # 100000.00
    assert income_statement["total_income"] == expected_total
    assert income_statement["net_income"] == expected_total
    assert balance_sheet["total_assets"] == expected_total
    assert balance_sheet["is_balanced"] is True
    assert cash_flow["summary"]["ending_cash"] == expected_total
    assert elapsed < LATENCY_BUDGET_SECONDS, (
        f"year-scale reporting took {elapsed:.2f}s (budget {LATENCY_BUDGET_SECONDS}s)"
    )
