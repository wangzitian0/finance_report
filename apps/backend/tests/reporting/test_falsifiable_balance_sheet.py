"""AC-reporting.balance-sheet.7: Adversarial falsifiable tests for balance sheet equation and currency translation."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.pricing.orm.market_data import FxRate
from src.reporting.base.balance_sheet_calculator import (
    calculate_balance_sheet_equation,
    calculate_currency_translation_adjustment,
)
from src.reporting.extension._core import _aggregate_balances_sql


def test_balance_sheet_equation_fails_when_asset_dropped_in_multicurrency():
    """AC-reporting.balance-sheet.7: Dropping an asset in multi-currency must evaluate to is_balanced=False.

    Proves that CTA adjustment cannot blind plug and mask dropped assets.
    """
    pnl_variance = Decimal("9.78")
    cta = calculate_currency_translation_adjustment(
        pnl_translation_variance=pnl_variance,
        is_multicurrency=True,
    )
    assert cta == Decimal("9.78")

    # Balanced state: assets = 25,737.69, liabilities = 0, equity = 10,000, net_income = 15,727.91, cta = 9.78
    balanced_totals = calculate_balance_sheet_equation(
        total_assets=Decimal("25737.69"),
        total_liabilities=Decimal("0.00"),
        total_equity=Decimal("10000.00"),
        net_income=Decimal("15727.91"),
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
        cta_adjustment=cta,
    )
    assert balanced_totals.is_balanced is True
    assert balanced_totals.equation_delta == Decimal("0.00")

    # MUTATION: 100.00 is lost from assets.
    # The equation MUST fail and not absorb the 100.00 loss into CTA.
    corrupted_totals = calculate_balance_sheet_equation(
        total_assets=Decimal("25637.69"),  # 100.00 missing!
        total_liabilities=Decimal("0.00"),
        total_equity=Decimal("10000.00"),
        net_income=Decimal("15727.91"),
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
        cta_adjustment=cta,
    )
    assert corrupted_totals.is_balanced is False
    assert corrupted_totals.equation_delta == Decimal("-100.00")


@pytest.mark.asyncio
async def test_aggregate_balances_excludes_fx_revaluation_entries(db: AsyncSession, test_user):
    """AC-reporting.balance-sheet.7: _aggregate_balances_sql excludes FX_REVALUATION entries to avoid double-counting."""
    as_of = date(2026, 3, 31)
    cash = Account(user_id=test_user.id, name="Cash USD", type=AccountType.ASSET, currency="USD", is_active=True)
    equity = Account(
        user_id=test_user.id, name="Owner Capital", type=AccountType.EQUITY, currency="SGD", is_active=True
    )
    fx_account = Account(
        user_id=test_user.id,
        name="Unrealized FX",
        code="SYS-FX-REVAL",
        type=AccountType.EQUITY,
        currency="SGD",
        is_active=True,
    )
    db.add_all([cash, equity, fx_account])
    db.add(FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.40"), rate_date=as_of, source="test"))
    await db.flush()

    # 1. Normal posted transaction: 1000 USD at rate 1.35
    entry1 = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 3, 1),
        memo="Initial deposit",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry1)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry1.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="USD",
                fx_rate=Decimal("1.35"),
            ),
            JournalLine(
                journal_entry_id=entry1.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("1350.00"),
                currency="SGD",
                fx_rate=None,
            ),
        ]
    )
    await db.flush()

    # 2. FX_REVALUATION entry: revalues USD cash by +50 SGD (debit cash, credit SYS-FX-REVAL)
    reval_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=as_of,
        memo="FX Revaluation",
        source_type=JournalEntrySourceType.FX_REVALUATION,
        status=JournalEntryStatus.POSTED,
    )
    db.add(reval_entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=reval_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("50.00"),
                currency="SGD",
                fx_rate=Decimal("1.0"),
            ),
            JournalLine(
                journal_entry_id=reval_entry.id,
                account_id=fx_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("50.00"),
                currency="SGD",
                fx_rate=Decimal("1.0"),
            ),
        ]
    )
    await db.flush()

    # Aggregate balances in SGD. Spot rate for USD on 2026-03-31 is assumed 1.40.
    # Cash USD should have ONLY the 1000 USD line (revalued at spot 1.40 = 1400 SGD).
    # It must NOT include the +50 SGD revaluation line (which would make it 1450 SGD!).
    balances = await _aggregate_balances_sql(
        db,
        test_user.id,
        (AccountType.ASSET, AccountType.EQUITY),
        target_currency="SGD",
        as_of_date=as_of,
    )

    # Cash balance at 1.40 spot rate: 1000 * 1.40 = 1400.00 SGD
    assert balances.get(cash.id) == Decimal("1400.00"), (
        f"Expected 1400.00 without FX_REVALUATION, got {balances.get(cash.id)}"
    )
    # SYS-FX-REVAL should have 0 balance in aggregate balances (it is excluded from ledger lines so unrealized_fx can contribute separately)
    assert balances.get(fx_account.id, Decimal("0.00")) == Decimal("0.00"), (
        f"Expected 0.00 for fx_account, got {balances.get(fx_account.id)}"
    )


@pytest.mark.asyncio
async def test_balance_sheet_cta_and_aggregation_falsifiability(db: AsyncSession, test_user):
    """AC-reporting.balance-sheet.7: Multi-currency balance sheet calculates CTA without plugging and excludes FX_REVALUATION from SQL aggregates."""
    await test_aggregate_balances_excludes_fx_revaluation_entries(db, test_user)
    test_balance_sheet_equation_fails_when_asset_dropped_in_multicurrency()
