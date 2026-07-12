"""Issue #387: Balance sheet includes portfolio and manual valuation components.

AC18.4.1: Reports read Layer 3 TransactionClassification category breakdowns.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer2 import AssetType, AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.layer3 import (
    ClassificationRule,
    ClassificationStatus,
    CostBasisMethod,
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
    RuleType,
    TransactionClassification,
)
from src.pricing import ValuationService
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_income_statement,
    get_net_worth_allocation_schedule,
)


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
            dedup_hash=f"position-{uuid4().hex}",
            source_documents={},
        )
    )


async def _create_valuation(
    db: AsyncSession,
    user_id,
    *,
    component_type: ManualValuationComponentType,
    component_name: str,
    liquidity_class: ManualValuationLiquidityClass,
    value: Decimal,
    currency: str,
    as_of_date: date,
) -> ManualValuationSnapshot:
    snapshot = ManualValuationSnapshot(
        user_id=user_id,
        component_type=component_type,
        liquidity_class=liquidity_class,
        value=value,
        currency=currency,
        as_of_date=as_of_date,
        source=component_name,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


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
    assert report["unrealized_fx_gain_loss"] == Decimal("0.00")
    assert report["net_worth_adjustment_gain_loss"] == Decimal("500.00")
    assert any(line["amount"] == Decimal("500.00") for line in report["assets"])


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


async def test_current_balance_sheet_uses_latest_future_brokerage_snapshot(db: AsyncSession, test_user):
    """AC-extraction.813.10: Current balance sheet includes latest imported brokerage snapshots."""
    report_date = date.today()
    snapshot_date = (
        date(report_date.year + 1, 1, 31)
        if report_date.month == 12
        else date(
            report_date.year,
            report_date.month + 1,
            1,
        )
    )
    brokerage = await _create_account(db, test_user.id, name="Moomoo", account_type=AccountType.ASSET)
    await _create_position_snapshot(
        db,
        test_user.id,
        brokerage,
        asset_identifier="FULLERTON_SGD_MMF",
        quantity=Decimal("100"),
        cost_basis=Decimal("0.00"),
        market_value=Decimal("1234.00"),
        as_of_date=snapshot_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1234.00")
    assert report["net_worth_adjustment_gain_loss"] == Decimal("1234.00")
    assert any(line["name"] == "Moomoo market valuation adjustment" for line in report["assets"])


async def test_portfolio_market_adjustment_survives_unrelated_negative_asset_lines(db: AsyncSession, test_user):
    """AC8.13.18: Portfolio valuation lines remain correct when total assets are lower."""
    report_date = date(2025, 3, 31)
    bank = await _create_account(db, test_user.id, name="Bank - Main", account_type=AccountType.ASSET)
    brokerage = await _create_account(db, test_user.id, name="Moomoo", account_type=AccountType.ASSET)
    equity = await _create_account(db, test_user.id, name="Owner Equity", account_type=AccountType.EQUITY)
    await _post_balanced_entry(
        db,
        test_user.id,
        entry_date=report_date,
        debit_account=equity,
        credit_account=bank,
        amount=Decimal("578.78"),
    )
    await _create_position_snapshot(
        db,
        test_user.id,
        brokerage,
        asset_identifier="FULLERTON_SGD_MMF",
        quantity=Decimal("100"),
        cost_basis=Decimal("0.00"),
        market_value=Decimal("1250.50"),
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")
    valuation_lines = [line for line in report["assets"] if "market valuation adjustment" in str(line["name"]).lower()]
    valuation_total = sum((line["amount"] for line in valuation_lines), Decimal("0.00"))

    assert report["total_assets"] == Decimal("671.72")
    assert valuation_total == Decimal("1250.50")
    assert report["net_worth_adjustment_gain_loss"] == Decimal("1250.50")
    assert valuation_total > report["total_assets"]


async def test_portfolio_market_adjustment_preserves_broker_cash_balance(db: AsyncSession, test_user):
    """AC17.5.4: Broker cash remains in net worth when positions are adjusted to market value."""
    report_date = date(2025, 3, 31)
    brokerage = await _create_account(db, test_user.id, name="Moomoo", account_type=AccountType.ASSET)
    equity = await _create_account(db, test_user.id, name="Owner Equity", account_type=AccountType.EQUITY)
    await _post_balanced_entry(
        db,
        test_user.id,
        entry_date=report_date,
        debit_account=brokerage,
        credit_account=equity,
        amount=Decimal("1200.00"),
    )
    await _create_position_snapshot(
        db,
        test_user.id,
        brokerage,
        asset_identifier="NVDA",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000.00"),
        market_value=Decimal("1500.00"),
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1700.00")
    assert report["total_equity"] == Decimal("1200.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("0.00")
    assert report["net_worth_adjustment_gain_loss"] == Decimal("500.00")
    assert any(line["amount"] == Decimal("500.00") for line in report["assets"])


async def test_portfolio_without_market_price_is_skipped(db: AsyncSession, test_user):
    """AC17.5.4: Positions without market prices do not block balance sheet generation."""
    report_date = date(2025, 3, 31)
    brokerage = await _create_account(db, test_user.id, name="Moomoo", account_type=AccountType.ASSET)
    db.add(
        ManagedPosition(
            user_id=test_user.id,
            account_id=brokerage.id,
            asset_identifier="MISSING",
            quantity=Decimal("10"),
            cost_basis=Decimal("1000.00"),
            currency="SGD",
            acquisition_date=report_date,
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("0.00")
    assert not any("market valuation adjustment" in line["name"] for line in report["assets"])


async def test_portfolio_market_adjustment_skips_zero_delta(db: AsyncSession, test_user):
    """AC17.5.4: A position already carried at market value does not add a zero adjustment line."""
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
        asset_identifier="MSFT",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000.00"),
        market_value=Decimal("1000.00"),
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1000.00")
    assert not any("market valuation adjustment" in line["name"] for line in report["assets"])


async def test_portfolio_market_adjustment_converts_position_currency(db: AsyncSession, test_user):
    """AC17.5.4: Foreign-currency broker positions are converted into report currency."""
    acquisition_date = date(2025, 1, 15)
    report_date = date(2025, 3, 31)
    brokerage = await _create_account(db, test_user.id, name="Moomoo USD", account_type=AccountType.ASSET)
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=acquisition_date,
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.35"),
                rate_date=report_date,
                source="test",
            ),
        ]
    )
    await _create_position_snapshot(
        db,
        test_user.id,
        brokerage,
        asset_identifier="GOOG",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000.00"),
        market_value=Decimal("1500.00"),
        as_of_date=report_date,
        currency="USD",
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("2025.00")
    assert any(line["amount"] == Decimal("2025.00") for line in report["assets"])


async def test_foreign_currency_portfolio_missing_fx_rate_raises_report_error(db: AsyncSession, test_user):
    """AC17.5.4: Missing FX for foreign-currency positions fails explicitly."""
    report_date = date(2025, 3, 31)
    brokerage = await _create_account(db, test_user.id, name="Moomoo USD", account_type=AccountType.ASSET)
    await _create_position_snapshot(
        db,
        test_user.id,
        brokerage,
        asset_identifier="META",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000.00"),
        market_value=Decimal("1500.00"),
        as_of_date=report_date,
        currency="USD",
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")


async def test_manual_property_and_mortgage_valuations_change_net_worth(db: AsyncSession, test_user):
    """AC5.7.3: Manual asset and liability valuation snapshots are included in balance sheet totals."""
    report_date = date(2025, 3, 31)
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        component_name="Singapore Condo",
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        value=Decimal("1200000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.MORTGAGE_BALANCE,
        component_name="Singapore Condo Mortgage",
        liquidity_class=ManualValuationLiquidityClass.LIABILITY,
        value=Decimal("600000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1200000.00")
    assert report["total_liabilities"] == Decimal("600000.00")
    assert report["total_assets"] - report["total_liabilities"] == Decimal("600000.00")


async def test_balance_sheet_can_exclude_restricted_and_illiquid_valuation_assets(
    db: AsyncSession,
    test_user,
):
    """AC11.9.3: Balance sheet restricted toggle excludes restricted and illiquid asset snapshots."""
    report_date = date(2025, 3, 31)
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        component_name="Singapore Condo",
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        value=Decimal("1200000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.ESOP,
        component_name="Employer ESOP",
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        value=Decimal("42000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.TAX_REFUND,
        component_name="IRAS refund",
        liquidity_class=ManualValuationLiquidityClass.LIQUID,
        value=Decimal("1200.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.MORTGAGE_BALANCE,
        component_name="Singapore Condo Mortgage",
        liquidity_class=ManualValuationLiquidityClass.LIABILITY,
        value=Decimal("600000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await db.commit()

    liquid_report = await generate_balance_sheet(
        db,
        test_user.id,
        as_of_date=report_date,
        currency="SGD",
        include_restricted=False,
    )
    full_report = await generate_balance_sheet(
        db,
        test_user.id,
        as_of_date=report_date,
        currency="SGD",
        include_restricted=True,
    )

    assert liquid_report["total_assets"] == Decimal("1200.00")
    assert liquid_report["total_liabilities"] == Decimal("600000.00")
    assert full_report["total_assets"] == Decimal("1243200.00")
    assert full_report["total_liabilities"] == Decimal("600000.00")


async def test_AC11_20_1_retirement_and_benefit_assets_are_restricted_assets_in_balance_sheet(
    db: AsyncSession,
    test_user,
):
    """AC-reporting.net-worth-components.1: AC11.20.1: Retirement and benefit account values are restricted assets in full net worth."""
    report_date = date(2026, 6, 18)
    service = ValuationService()
    fixtures = [
        (ManualValuationComponentType.RETIREMENT_ACCOUNT, "401k statement", Decimal("100000.00")),
        (
            ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT,
            "China social security personal account",
            Decimal("12000.00"),
        ),
        (ManualValuationComponentType.CPF_BALANCE, "CPF statement", Decimal("50000.00")),
        (ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET, "Supplementary retirement plan", Decimal("15000.00")),
        (ManualValuationComponentType.INSURANCE_CASH_VALUE, "Whole life cash surrender value", Decimal("8000.00")),
    ]

    snapshots = [
        await service.create_valuation_snapshot(
            db,
            test_user.id,
            component_type=component_type,
            as_of_date=report_date,
            value=value,
            currency="SGD",
            source=source,
        )
        for component_type, source, value in fixtures
    ]
    await db.commit()

    assert {snapshot.liquidity_class for snapshot in snapshots} == {ManualValuationLiquidityClass.RESTRICTED}

    liquid_report = await generate_balance_sheet(
        db,
        test_user.id,
        as_of_date=report_date,
        currency="SGD",
        include_restricted=False,
    )
    full_report = await generate_balance_sheet(
        db,
        test_user.id,
        as_of_date=report_date,
        currency="SGD",
        include_restricted=True,
    )

    assert liquid_report["total_assets"] == Decimal("0.00")
    assert full_report["total_assets"] == Decimal("185000.00")
    assert full_report["net_worth_adjustment_gain_loss"] == Decimal("185000.00")


async def test_AC11_20_2_net_worth_allocation_groups_retirement_and_benefit_assets(
    db: AsyncSession,
    test_user,
):
    """AC-reporting.net-worth-components.2: AC11.20.2: Retirement and benefit values have a dedicated allocation asset class."""
    report_date = date(2026, 6, 18)
    fixtures = [
        (ManualValuationComponentType.RETIREMENT_ACCOUNT, "401k statement", Decimal("100000.00")),
        (
            ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT,
            "China social security personal account",
            Decimal("12000.00"),
        ),
        (ManualValuationComponentType.CPF_BALANCE, "CPF statement", Decimal("50000.00")),
        (ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET, "Supplementary retirement plan", Decimal("15000.00")),
        (ManualValuationComponentType.INSURANCE_CASH_VALUE, "Whole life cash surrender value", Decimal("8000.00")),
    ]
    for component_type, source, value in fixtures:
        await _create_valuation(
            db,
            test_user.id,
            component_type=component_type,
            component_name=source,
            liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
            value=value,
            currency="SGD",
            as_of_date=report_date,
        )
    await db.commit()

    schedule = await get_net_worth_allocation_schedule(
        db,
        test_user.id,
        as_of_date=report_date,
        currency="SGD",
        include_restricted=True,
    )

    rows = {(row["asset_class"], row["liquidity_class"], row["source_currency"]): row for row in schedule["rows"]}
    row = rows[("retirement_and_benefit_assets", "restricted", "SGD")]
    assert schedule["total_assets"] == Decimal("185000.00")
    assert schedule["net_worth"] == Decimal("185000.00")
    assert row["value"] == Decimal("185000.00")
    assert row["percentage_of_net_worth"] == Decimal("100.00")
    assert row["source_line_count"] == 5


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
        component_type=ManualValuationComponentType.RSU,
        component_name="Employer RSU",
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        value=Decimal("1000.00"),
        currency="USD",
        as_of_date=report_date,
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")

    assert report["total_assets"] == Decimal("1350.00")
    assert report["assets"][0]["amount"] == Decimal("1350.00")


async def test_manual_valuation_missing_fx_rate_raises_report_error(db: AsyncSession, test_user):
    """AC5.7.3: Missing FX for a manual valuation fails report generation explicitly."""
    report_date = date(2025, 3, 31)
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.RSU,
        component_name="Employer RSU",
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        value=Decimal("1000.00"),
        currency="USD",
        as_of_date=report_date,
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")


async def test_AC17_14_2_net_worth_allocation_groups_balance_sheet_sources(
    db: AsyncSession,
    test_user,
):
    """AC17.14.2: Net-worth allocation rows group balance-sheet sources and reconcile to net worth."""
    report_date = date(2025, 3, 31)
    bank = await _create_account(db, test_user.id, name="Main Bank", account_type=AccountType.ASSET)
    brokerage = await _create_account(db, test_user.id, name="Moomoo", account_type=AccountType.ASSET)
    equity = await _create_account(db, test_user.id, name="Owner Equity", account_type=AccountType.EQUITY)
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=report_date,
            source="test",
        )
    )
    await _post_balanced_entry(
        db,
        test_user.id,
        entry_date=report_date,
        debit_account=bank,
        credit_account=equity,
        amount=Decimal("5000.00"),
    )
    await _post_balanced_entry(
        db,
        test_user.id,
        entry_date=report_date,
        debit_account=brokerage,
        credit_account=equity,
        amount=Decimal("1200.00"),
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
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        component_name="Singapore Condo",
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        value=Decimal("10000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.MORTGAGE_BALANCE,
        component_name="Singapore Condo Mortgage",
        liquidity_class=ManualValuationLiquidityClass.LIABILITY,
        value=Decimal("4000.00"),
        currency="SGD",
        as_of_date=report_date,
    )
    await _create_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.RSU,
        component_name="Employer RSU",
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        value=Decimal("1000.00"),
        currency="USD",
        as_of_date=report_date,
    )
    await db.commit()

    schedule = await get_net_worth_allocation_schedule(
        db,
        test_user.id,
        as_of_date=report_date,
        currency="SGD",
        include_restricted=True,
    )

    rows = {(row["asset_class"], row["liquidity_class"], row["source_currency"]): row for row in schedule["rows"]}
    assert schedule["total_assets"] == Decimal("18050.00")
    assert schedule["total_liabilities"] == Decimal("4000.00")
    assert schedule["net_worth"] == Decimal("14050.00")
    assert sum((row["value"] for row in schedule["rows"]), Decimal("0.00")) == schedule["net_worth"]
    assert rows[("cash", "liquid", "SGD")]["value"] == Decimal("5200.00")
    assert rows[("public_equity", "liquid", "SGD")]["value"] == Decimal("1500.00")
    assert rows[("restricted_comp", "restricted", "USD")]["value"] == Decimal("1350.00")
    assert rows[("real_estate", "illiquid", "SGD")]["value"] == Decimal("10000.00")
    assert rows[("real_estate", "liability", "SGD")]["value"] == Decimal("-4000.00")
    assert rows[("public_equity", "liquid", "SGD")]["percentage_of_net_worth"] == Decimal("10.68")
    assert rows[("cash", "liquid", "SGD")]["source_line_count"] == 2
    assert rows[("public_equity", "liquid", "SGD")]["source_line_count"] == 2
    assert all(row["source_lines"] for row in schedule["rows"])


async def test_income_statement_includes_applied_classification_breakdown(db: AsyncSession, test_user):
    """AC-reporting.layer3.1 · AC-reporting.layer3.3: AC18.4.4: Income statements include applied Layer 3 classification coverage."""
    report_date = date(2025, 3, 31)
    income = await _create_account(db, test_user.id, name="Salary", account_type=AccountType.INCOME)
    atomic = AtomicTransaction(
        user_id=test_user.id,
        txn_date=report_date,
        amount=Decimal("1000.00"),
        direction=TransactionDirection.IN,
        description="Monthly salary",
        currency="SGD",
        dedup_hash=f"classification-{uuid4()}",
        source_documents=[],
    )
    db.add(atomic)
    await db.flush()
    rule = ClassificationRule(
        user_id=test_user.id,
        version_number=1,
        effective_date=report_date,
        rule_name=f"Salary rule {uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["salary"]},
        default_account_id=income.id,
        created_by=test_user.id,
    )
    db.add(rule)
    await db.flush()
    db.add(
        TransactionClassification(
            atomic_txn_id=atomic.id,
            rule_version_id=rule.id,
            account_id=income.id,
            confidence_score=95,
            status=ClassificationStatus.APPLIED,
        )
    )
    await db.commit()

    report = await generate_income_statement(
        db,
        test_user.id,
        start_date=report_date,
        end_date=report_date,
        currency="SGD",
    )

    assert report["classification_breakdown"] == [
        {
            "account_name": "Salary",
            "account_type": "INCOME",
            "classified_count": 1,
            "avg_confidence": 95.0,
        }
    ]
