"""Issue #197: reporting uses calculated FX revaluation and exposes FX warnings."""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer3 import ManualValuationComponentType, ManualValuationLiquidityClass, ManualValuationSnapshot
from src.pricing.orm.market_data import FxRate
from src.reporting import generate_balance_sheet, generate_income_statement
from src.services.fx import get_average_rate


async def _account(db: AsyncSession, user_id, name: str, account_type: AccountType, currency: str) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency, is_active=True)
    db.add(account)
    await db.flush()
    return account


async def test_balance_sheet_fx_revaluation_is_calculated_not_plugged(db: AsyncSession, test_user):
    """AC5.1.2: FX gain/loss is historical-cost revaluation, not the balance sheet plug."""
    report_date = date(2025, 1, 31)
    usd_cash = await _account(db, test_user.id, "USD Cash", AccountType.ASSET, "USD")
    owner_equity = await _account(db, test_user.id, "Owner Equity", AccountType.EQUITY, "SGD")
    db.add(
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=report_date, source="test")
    )

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2025, 1, 15),
        memo="USD deposit at historical cost",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=owner_equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("1300.00"),
                currency="SGD",
                fx_rate=Decimal("1"),
            ),
        ]
    )
    db.add(
        ManualValuationSnapshot(
            user_id=test_user.id,
            component_type=ManualValuationComponentType.OTHER_ASSET,
            liquidity_class=ManualValuationLiquidityClass.LIQUID,
            value=Decimal("200.00"),
            currency="SGD",
            as_of_date=report_date,
            source="Manual asset",
        )
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1550.00")
    assert report["total_equity"] == Decimal("1300.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("50.00")
    assert report["net_worth_adjustment_gain_loss"] == Decimal("200.00")
    assert report["equation_delta"] == Decimal("0.00")
    assert report["is_balanced"] is True


async def test_income_statement_includes_average_rate_fallback_warning(db: AsyncSession, test_user):
    """AC-reporting.kpis.3: AC5.6.7: Report output lists currencies that used average-rate spot fallback."""
    start_date = date(2025, 1, 1)
    end_date = date(2025, 1, 31)
    cash = await _account(db, test_user.id, "USD Cash", AccountType.ASSET, "USD")
    income = await _account(db, test_user.id, "USD Salary", AccountType.INCOME, "USD")
    db.add(
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.50"), rate_date=date(2024, 12, 31), source="test"
        )
    )

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2025, 1, 15),
        memo="USD salary",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
                fx_rate=Decimal("1.50"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
                fx_rate=Decimal("1.50"),
            ),
        ]
    )
    await db.commit()

    assert await get_average_rate(db, "USD", "SGD", start_date, end_date) == Decimal("1.50")

    report = await generate_income_statement(
        db,
        test_user.id,
        start_date=start_date,
        end_date=end_date,
        currency="SGD",
    )

    assert report["net_income"] == Decimal("150.00")
    assert report["fx_warnings"] == [
        {
            "type": "average_rate_fallback",
            "base_currency": "USD",
            "quote_currency": "SGD",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
        }
    ]
