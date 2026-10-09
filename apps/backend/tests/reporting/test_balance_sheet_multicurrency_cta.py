"""AC-reporting.balance-sheet.2: Tests for Multi-Currency Foreign Currency Translation Adjustment (CTA) on the Balance Sheet."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing.orm.market_data import FxRate
from src.reporting import generate_balance_sheet
from src.reporting.extension._core import _aggregate_equity_translation_variance_sql


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


async def test_aggregate_equity_translation_variance_hist_rate_lookup(db: AsyncSession, user_id):
    """Verify equity translation variance resolves historical rate when target currency differs from base currency."""
    checking_usd = Account(user_id=user_id, name="Checking USD Eq", type=AccountType.ASSET, currency="USD")
    equity_usd = Account(user_id=user_id, name="Equity USD", type=AccountType.EQUITY, currency="USD")
    db.add_all([checking_usd, equity_usd])
    await db.commit()
    await db.refresh(checking_usd)
    await db.refresh(equity_usd)

    # FX rates:
    # 1. USD -> SGD (base currency) for journal line validation
    # 2. USD -> HKD (target currency) spot on 2025-01-31 (7.80) and historical on 2025-01-05 (7.75)
    fx_rates = [
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=date(2025, 1, 5), source="test"
        ),
        FxRate(
            base_currency="USD", quote_currency="HKD", rate=Decimal("7.75"), rate_date=date(2025, 1, 5), source="test"
        ),
        FxRate(
            base_currency="USD", quote_currency="HKD", rate=Decimal("7.80"), rate_date=date(2025, 1, 31), source="test"
        ),
    ]
    db.add_all(fx_rates)
    await db.commit()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 5),
        memo="Opening Capital USD",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=checking_usd.id,
        direction=Direction.DEBIT,
        amount=Decimal("500.00"),
        currency="USD",
        fx_rate=Decimal("1.30"),
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=equity_usd.id,
        direction=Direction.CREDIT,
        amount=Decimal("500.00"),
        currency="USD",
        fx_rate=Decimal("1.30"),
    )
    db.add_all([line_debit, line_credit])
    await db.commit()

    variance = await _aggregate_equity_translation_variance_sql(
        db,
        user_id,
        target_currency="HKD",
        as_of_date=date(2025, 1, 31),
    )
    # 500 * (7.80 - 7.75) = 25.00 HKD
    assert variance == Decimal("25.00")


async def test_aggregate_equity_translation_variance_missing_hist_rate_fallback(db: AsyncSession, user_id):
    """When historical rate is absent and lazy_load=False, falls back to spot rate safely."""
    checking_eur = Account(user_id=user_id, name="Checking EUR Eq", type=AccountType.ASSET, currency="EUR")
    equity_eur = Account(user_id=user_id, name="Equity EUR", type=AccountType.EQUITY, currency="EUR")
    db.add_all([checking_eur, equity_eur])
    await db.commit()
    await db.refresh(checking_eur)
    await db.refresh(equity_eur)

    # EUR -> SGD for journal line validation
    # EUR -> HKD spot on 2025-01-31 provided, but historical rate on 2025-01-05 is missing
    fx_rates = [
        FxRate(
            base_currency="EUR", quote_currency="SGD", rate=Decimal("1.45"), rate_date=date(2025, 1, 5), source="test"
        ),
        FxRate(
            base_currency="EUR", quote_currency="HKD", rate=Decimal("8.50"), rate_date=date(2025, 1, 31), source="test"
        ),
    ]
    db.add_all(fx_rates)
    await db.commit()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 5),
        memo="Opening EUR Capital",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=checking_eur.id,
        direction=Direction.DEBIT,
        amount=Decimal("300.00"),
        currency="EUR",
        fx_rate=Decimal("1.45"),
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=equity_eur.id,
        direction=Direction.CREDIT,
        amount=Decimal("300.00"),
        currency="EUR",
        fx_rate=Decimal("1.45"),
    )
    db.add_all([line_debit, line_credit])
    await db.commit()

    variance = await _aggregate_equity_translation_variance_sql(
        db,
        user_id,
        target_currency="HKD",
        as_of_date=date(2025, 1, 31),
    )
    # spot_rate (8.50) - fallback spot_rate (8.50) = 0.00
    assert variance == Decimal("0.00")
