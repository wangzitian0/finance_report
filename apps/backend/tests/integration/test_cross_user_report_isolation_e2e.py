from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration
from src.audit import JournalEntrySourceType
from src.identity import User
from src.ledger import AccountType, post_journal_entry
from src.pricing import ManualValuationComponentType, ValuationService
from src.reporting import generate_balance_sheet, generate_income_statement
from tests.factories import AccountFactory, UserFactory
from tests.ledger._ledger_helpers import create_anchored_test_journal_entry as create_journal_entry


async def _seed_user(db: AsyncSession, uid, prefix: str, cap: str, sal: str) -> None:
    bank = await AccountFactory.create_async(db, user_id=uid, name=f"{prefix} Bank", type=AccountType.ASSET)
    eq = await AccountFactory.create_async(db, user_id=uid, name=f"{prefix} Equity", type=AccountType.EQUITY)
    sal_acc = await AccountFactory.create_async(db, user_id=uid, name=f"{prefix} Salary", type=AccountType.INCOME)
    for credit, amt in ((eq, Decimal(cap)), (sal_acc, Decimal(sal))):
        entry = await create_journal_entry(
            db=db,
            user_id=uid,
            entry_date=date(2026, 3, 15),
            memo="iso",
            lines_data=[
                {"account_id": bank.id, "direction": "DEBIT", "amount": amt, "currency": "SGD"},
                {"account_id": credit.id, "direction": "CREDIT", "amount": amt, "currency": "SGD"},
            ],
            source_type=JournalEntrySourceType.MANUAL,
        )
        await post_journal_entry(db, entry.id, uid)


async def test_reports_exclude_other_users_entries(db: AsyncSession, test_user: User) -> None:
    user_a, user_b = test_user.id, (await UserFactory.create_async(db)).id
    await _seed_user(db, user_a, "A", "1000.00", "500.00")
    await _seed_user(db, user_b, "B", "9999.00", "7777.00")
    await db.commit()

    p_start, p_end = date(2026, 1, 1), date(2026, 12, 31)
    a_bs = await generate_balance_sheet(db, user_a, as_of_date=p_end, currency="SGD")
    a_is = await generate_income_statement(db, user_a, start_date=p_start, end_date=p_end, currency="SGD")
    b_bs = await generate_balance_sheet(db, user_b, as_of_date=p_end, currency="SGD")
    assert (
        a_bs["total_assets"],
        a_bs["is_balanced"],
        a_is["total_income"],
        a_is["net_income"],
        b_bs["total_assets"],
    ) == (Decimal("1500.00"), True, Decimal("500.00"), Decimal("500.00"), Decimal("17776.00"))
    a_lines = {line["name"] for sec in ("assets", "liabilities", "equity") for line in a_bs[sec]}
    assert not any(name.startswith("B ") for name in a_lines), a_lines

    service = ValuationService()
    await service.create_valuation_snapshot(
        db,
        user_id=user_a,
        value=Decimal("200000.00"),
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=p_end,
        currency="SGD",
        source="A appraisal",
    )
    await service.create_valuation_snapshot(
        db,
        user_id=user_b,
        value=Decimal("800000.00"),
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=p_end,
        currency="SGD",
        source="B appraisal",
    )
    await db.commit()
    assert (
        (await service.get_latest_valuation_components(db, user_a, as_of_date=p_end)).total_assets,
        (await service.get_latest_valuation_components(db, user_b, as_of_date=p_end)).total_assets,
    ) == (Decimal("200000.00"), Decimal("800000.00"))
