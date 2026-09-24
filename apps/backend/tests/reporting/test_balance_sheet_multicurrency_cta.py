"""AC-reporting.balance-sheet.2: Tests for Multi-Currency Foreign Currency Translation Adjustment (CTA) on the Balance Sheet."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing.orm.market_data import FxRate
from src.reporting import generate_balance_sheet


@pytest.fixture
def user_id(test_user):
    return test_user.id


async def test_balance_sheet_multicurrency_cta_resolution(db: AsyncSession, user_id):
    """Test that multi-currency spot vs average translation divergence is recognized as CTA.

    When assets in USD are converted at spot rate (e.g. 1.40) and revenue in USD
    is converted at period-average rate (e.g. 1.30), the balance sheet equation
    Assets = Liabilities + Equity + NetIncome + UnrealizedFX + NetWorthAdj + CTA
    remains strictly balanced with equation_delta == Decimal("0.00").
    """
    # 1. Accounts
    checking_usd = Account(user_id=user_id, name="Checking USD", type=AccountType.ASSET, currency="USD")
    income_usd = Account(user_id=user_id, name="Revenue USD", type=AccountType.INCOME, currency="USD")
    db.add_all([checking_usd, income_usd])
    await db.commit()
    await db.refresh(checking_usd)
    await db.refresh(income_usd)

    # 2. FX Rates: Spot rate on 2025-01-31 is 1.40, Average rate across period is 1.30
    fx_rates = [
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.20"), rate_date=date(2025, 1, 1), source="test"
        ),
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=date(2025, 1, 15), source="test"
        ),
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.40"), rate_date=date(2025, 1, 31), source="test"
        ),
    ]
    db.add_all(fx_rates)
    await db.commit()

    # 3. Post a journal entry: 1000 USD revenue received in Checking USD on Jan 5 (historical rate 1.20)
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 5),
        memo="Client Payment USD",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=checking_usd.id,
        direction=Direction.DEBIT,
        amount=Decimal("1000.00"),
        currency="USD",
        fx_rate=Decimal("1.20"),
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=income_usd.id,
        direction=Direction.CREDIT,
        amount=Decimal("1000.00"),
        currency="USD",
        fx_rate=Decimal("1.20"),
    )
    db.add_all([line_debit, line_credit])
    await db.commit()

    # 4. Generate Balance Sheet in SGD as of 2025-01-31
    bs = await generate_balance_sheet(
        db,
        user_id,
        as_of_date=date(2025, 1, 31),
        currency="SGD",
    )

    # Spot rate on 2025-01-31 is 1.40 -> Assets = 1,400.00 SGD
    assert bs["total_assets"] == Decimal("1400.00")
    # Average rate is 1.30 -> Net Income = 1,300.00 SGD
    assert bs["net_income"] == Decimal("1300.00")
    # Unrealized FX gain (1.40 spot - 1.20 book) = 200.00 SGD
    assert bs["unrealized_fx_gain_loss"] == Decimal("200.00")
    # Total Assets (1400) - [Net Income (1300) + Unrealized FX (200)] = -100.00 SGD translation variance
    assert bs["cta_adjustment"] == Decimal("-100.00")
    # Equation delta must be exactly 0.00 and is_balanced must be True!
    assert bs["equation_delta"] == Decimal("0.00")
    assert bs["is_balanced"] is True
