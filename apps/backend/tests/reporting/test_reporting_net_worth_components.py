"""Issue #387: Balance sheet includes portfolio and manual valuation components."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    FxRate,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ValuationComponentType,
    ValuationConfidence,
    ValuationSide,
    ValuationSnapshot,
    ValuationSource,
)
from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.services.reporting import generate_balance_sheet


async def _create_account(
    db: AsyncSession,
    user_id,
    *,
    name: str,
    account_type: AccountType,
    currency: str = "SGD",
) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _post_balanced_entry(
    db: AsyncSession,
    user_id,
    *,
    entry_date: date,
    debit_account: Account,
    credit_account: Account,
    amount: Decimal,
    currency: str = "SGD",
) -> None:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo="Investment cost basis",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit_account.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency=currency,
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit_account.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency=currency,
            ),
        ]
    )


async def _create_position_snapshot(
    db: AsyncSession,
    user_id,
    account: Account,
    *,
    asset_identifier: str,
    quantity: Decimal,
    cost_basis: Decimal,
    market_value: Decimal,
    as_of_date: date,
    currency: str = "SGD",
) -> None:
    db.add(
        ManagedPosition(
            user_id=user_id,
            account_id=account.id,
            asset_identifier=asset_identifier,
            quantity=quantity,
            cost_basis=cost_basis,
            currency=currency,
            acquisition_date=as_of_date,
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    db.add(
        AtomicPosition(
            user_id=user_id,
            snapshot_date=as_of_date,
            asset_identifier=asset_identifier,
            broker=account.name,
            quantity=quantity,
            market_value=market_value,
            currency=currency,
            asset_type=AssetType.STOCK,
            sector="Technology",
            geography="US",
            dedup_hash=f"{user_id}-{asset_identifier}-{as_of_date.isoformat()}",
            source_documents={},
        )
    )


async def _create_valuation(
    db: AsyncSession,
    user_id,
    *,
    component_type: ValuationComponentType,
    component_name: str,
    side: ValuationSide,
    value: Decimal,
    currency: str,
    as_of_date: date,
) -> ValuationSnapshot:
    snapshot = ValuationSnapshot(
        user_id=user_id,
        component_type=component_type,
        component_name=component_name,
        side=side,
        value=value,
        currency=currency,
        as_of_date=as_of_date,
        source=ValuationSource.MANUAL,
        confidence=ValuationConfidence.MEDIUM,
        stale_after_days=90,
        include_in_total_net_worth=True,
        include_in_liquid_net_worth=False,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


@pytest.mark.asyncio
async def test_portfolio_market_value_updates_balance_sheet_without_double_counting(db: AsyncSession, test_user):
    """AC17.5.4: Broker market valuation adjusts ledger cost basis without double counting."""
    report_date = date(2025, 3, 31)
    brokerage = await _create_account(db, test_user.id, name="Moomoo", account_type=AccountType.ASSET)
    equity = await _create_account(db, test_user.id, name="Owner Equity", account_type=AccountType.EQUITY)
    await _post_balanced_entry(
        db,
        test_user.id,
        entry_date=report_date,
        debit_account=brokerage,
        credit_account=equity,
        amount=Decimal("1000.00"),
    )
    await _create_position_snapshot(
        db,
        test_user.id,
        brokerage,
        asset_identifier="AAPL",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000.00"),
        market_value=Decimal("1500.00"),
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1500.00")
    assert report["total_equity"] == Decimal("1000.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("500.00")
    assert any(line["amount"] == Decimal("500.00") for line in report["assets"])


@pytest.mark.asyncio
async def test_portfolio_market_value_counts_when_ledger_has_no_cost_basis(db: AsyncSession, test_user):
    """AC17.5.4: Broker positions with no journal cost basis still appear in net worth."""
    report_date = date(2025, 3, 31)
    brokerage = await _create_account(db, test_user.id, name="Moomoo", account_type=AccountType.ASSET)
    await _create_position_snapshot(
        db,
        test_user.id,
        brokerage,
        asset_identifier="TSLA",
        quantity=Decimal("5"),
        cost_basis=Decimal("0.00"),
        market_value=Decimal("1250.00"),
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1250.00")
    assert any(line["name"] == "Moomoo market valuation adjustment" for line in report["assets"])


@pytest.mark.asyncio
async def test_manual_property_and_mortgage_valuations_change_net_worth(db: AsyncSession, test_user):
    """AC5.7.3: Manual asset and liability valuation snapshots are included in balance sheet totals."""
    report_date = date(2025, 3, 31)
    await _create_valuation(
        db,
        test_user.id,
        component_type=ValuationComponentType.PROPERTY,
        component_name="Singapore Condo",
        side=ValuationSide.ASSET,
        value=Decimal("1200000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ValuationComponentType.MORTGAGE,
        component_name="Singapore Condo Mortgage",
        side=ValuationSide.LIABILITY,
        value=Decimal("600000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1200000.00")
    assert report["total_liabilities"] == Decimal("600000.00")
    assert report["total_assets"] - report["total_liabilities"] == Decimal("600000.00")


@pytest.mark.asyncio
async def test_manual_valuation_uses_as_of_historical_fx_rate(db: AsyncSession, test_user):
    """AC5.7.3: Non-base valuation snapshots use historical FX for the requested as-of date."""
    report_date = date(2025, 3, 31)
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=report_date,
            source="test",
        )
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ValuationComponentType.ESOP_RSU_OPTION,
        component_name="Employer RSU",
        side=ValuationSide.ASSET,
        value=Decimal("1000.00"),
        currency="USD",
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1350.00")
    assert report["assets"][0]["amount"] == Decimal("1350.00")
