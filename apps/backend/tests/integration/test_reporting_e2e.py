from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration
from src.ledger import AccountType, post_journal_entry
from src.pricing.orm.market_data import FxRate
from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement
from tests.factories import AccountFactory
from tests.ledger._ledger_helpers import create_anchored_test_journal_entry as create_journal_entry


async def test_multicurrency_reporting_cycle_reconciles_bs_is_cf(db: AsyncSession, test_user) -> None:
    uid, period_start, period_end = test_user.id, date(2026, 1, 1), date(2026, 1, 31)
    cash = await AccountFactory.create_async(db, user_id=uid, name="Cash SGD", code="1001", type=AccountType.ASSET)
    usd = await AccountFactory.create_async(db, user_id=uid, name="Broker Cash USD", code="1010", type=AccountType.ASSET, currency="USD")
    salary = await AccountFactory.create_async(db, user_id=uid, name="Salary", code="4001", type=AccountType.INCOME)
    expense = await AccountFactory.create_async(db, user_id=uid, name="Groceries", code="5001", type=AccountType.EXPENSE)
    equity = await AccountFactory.create_async(db, user_id=uid, name="Opening Equity", code="3001", type=AccountType.EQUITY)
    db.add_all([FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=d, source="test") for d in (date(2026, 1, 10), period_end)])
    for edate, memo, lines in (
        (period_start, "Opening capital", [{"account_id": cash.id, "direction": "DEBIT", "amount": Decimal("5000.00"), "currency": "SGD"}, {"account_id": equity.id, "direction": "CREDIT", "amount": Decimal("5000.00"), "currency": "SGD"}]),
        (date(2026, 1, 5), "Salary deposit", [{"account_id": cash.id, "direction": "DEBIT", "amount": Decimal("3000.00"), "currency": "SGD"}, {"account_id": salary.id, "direction": "CREDIT", "amount": Decimal("3000.00"), "currency": "SGD"}]),
        (date(2026, 1, 8), "Groceries", [{"account_id": expense.id, "direction": "DEBIT", "amount": Decimal("200.00"), "currency": "SGD"}, {"account_id": cash.id, "direction": "CREDIT", "amount": Decimal("200.00"), "currency": "SGD"}]),
        (date(2026, 1, 10), "USD dividend", [{"account_id": usd.id, "direction": "DEBIT", "amount": Decimal("100.00"), "currency": "USD", "fx_rate": Decimal("1.350000")}, {"account_id": salary.id, "direction": "CREDIT", "amount": Decimal("135.00"), "currency": "SGD"}]),
    ):
        entry = await create_journal_entry(db=db, user_id=uid, entry_date=edate, memo=memo, lines_data=lines)
        await post_journal_entry(db, entry.id, uid)
    await db.commit()

    bs = await generate_balance_sheet(db, uid, as_of_date=period_end, currency="SGD")
    inc = await generate_income_statement(db, uid, start_date=period_start, end_date=period_end, currency="SGD")
    cf = await generate_cash_flow(db, uid, start_date=period_start, end_date=period_end, currency="SGD")
    assert (bs["is_balanced"], bs["equation_delta"], bs["total_assets"], bs["total_equity"], inc["total_income"], inc["total_expenses"], inc["net_income"], cf["summary"]["beginning_cash"], cf["summary"]["ending_cash"], cf["summary"]["net_cash_flow"]) == (
        True, Decimal("0.00"), Decimal("7935.00"), Decimal("5000.00"), Decimal("3135.00"), Decimal("200.00"), Decimal("2935.00"), Decimal("0.00"), Decimal("7935.00"), Decimal("7935.00")
    )
