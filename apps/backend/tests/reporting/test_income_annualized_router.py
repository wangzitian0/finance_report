"""Behavioral coverage for annualized income and restricted holdings dashboard APIs."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType, Direction, FxRate, JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer3 import ManualValuationComponentType, ManualValuationLiquidityClass, ManualValuationSnapshot


async def test_annualized_income_endpoint_groups_last_12_month_income(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC11.8.1/AC5.6.4: GET /income/annualized returns salary, bonus, dividend, total, currency, and as_of."""
    salary = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    bonus = Account(user_id=test_user.id, name="Annual Bonus", type=AccountType.INCOME, currency="SGD")
    dividend = Account(user_id=test_user.id, name="Dividend Income", type=AccountType.INCOME, currency="SGD")
    other_income = Account(user_id=test_user.id, name="Interest Income", type=AccountType.INCOME, currency="SGD")
    old_salary = Account(user_id=test_user.id, name="Salary Prior Year", type=AccountType.INCOME, currency="SGD")
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    db.add_all([salary, bonus, dividend, other_income, old_salary, cash])
    await db.flush()

    current_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 1),
        memo="current income",
        status=JournalEntryStatus.POSTED,
    )
    old_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2024, 12, 31),
        memo="outside trailing window",
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([current_entry, old_entry])
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=current_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("137700.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=current_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("120000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=current_entry.id,
                account_id=bonus.id,
                direction=Direction.CREDIT,
                amount=Decimal("15000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=current_entry.id,
                account_id=dividend.id,
                direction=Direction.CREDIT,
                amount=Decimal("2400.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=current_entry.id,
                account_id=other_income.id,
                direction=Direction.CREDIT,
                amount=Decimal("300.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=old_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("999.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=old_entry.id,
                account_id=old_salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("999.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    response = await client.get("/income/annualized?as_of=2026-05-20")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "annualized_salary": "120000.00",
        "annualized_bonus": "15000.00",
        "annualized_dividend": "2400.00",
        "annualized_total": "137700.00",
        "currency": "SGD",
        "as_of": "2026-05-20",
    }


async def test_AC11_8_7_annualized_income_endpoint_converts_mixed_currency_totals(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC11.8.7: Dashboard annualized income totals use one reporting currency."""
    salary = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    dividend = Account(user_id=test_user.id, name="Dividend Income", type=AccountType.INCOME, currency="USD")
    sgd_cash = Account(user_id=test_user.id, name="SGD Cash", type=AccountType.ASSET, currency="SGD")
    usd_cash = Account(user_id=test_user.id, name="USD Cash", type=AccountType.ASSET, currency="USD")
    db.add_all([salary, dividend, sgd_cash, usd_cash])
    await db.flush()

    income_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 1),
        memo="mixed currency dashboard income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(income_entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=usd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("10.00"),
                currency="USD",
                fx_rate=Decimal("1.500000"),
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=dividend.id,
                direction=Direction.CREDIT,
                amount=Decimal("10.00"),
                currency="USD",
                fx_rate=Decimal("1.500000"),
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.500000"),
                rate_date=date(2026, 5, 1),
                source="test",
            ),
        ]
    )
    await db.commit()

    response = await client.get("/income/annualized?as_of=2026-05-20")

    assert response.status_code == 200
    assert response.json() == {
        "annualized_salary": "100.00",
        "annualized_bonus": "0.00",
        "annualized_dividend": "15.00",
        "annualized_total": "115.00",
        "currency": "SGD",
        "as_of": "2026-05-20",
    }


async def test_restricted_assets_endpoint_returns_latest_locked_holdings(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC11.8.3: GET /assets/restricted returns ESOP/RSU holdings with vesting metadata."""
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 1, 1),
                value=Decimal("10000.00"),
                currency="USD",
                source="SHOP-RSU",
                notes="25% annual vesting",
                reminder_date=date(2027, 1, 1),
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 5, 1),
                value=Decimal("12500.00"),
                currency="USD",
                source="SHOP-RSU",
                notes="25% annual vesting",
                reminder_date=date(2027, 1, 1),
            ),
        ]
    )
    await db.commit()

    response = await client.get("/assets/restricted?as_of_date=2026-05-20")

    assert response.status_code == 200
    assert response.json() == [
        {
            "ticker": "SHOP-RSU",
            "quantity": "1.000000",
            "vesting_schedule": "25% annual vesting",
            "unlock_date": "2027-01-01",
            "fair_value": "12500.00",
            "currency": "USD",
        }
    ]
