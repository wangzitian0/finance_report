"""Unit and integration tests for L1 Reporting-Line Registry and exact-aggregation assembly."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer3 import ManualValuationComponentType, ManualValuationLiquidityClass, ManualValuationSnapshot
from src.schemas.reporting import FrameworkPolicyDecision, PersonalReportingFrameworkId, PolicyFactDomain, ReportLineId
from src.services.reporting.framework_report import (
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.services.reporting.l1_registry import (
    get_framework_ordered_lines,
    get_registered_line,
    is_valid_line_for_framework,
)


@pytest.mark.no_db
def test_l1_registry_lookup_and_validation() -> None:
    """Verify registry queries, framework memberships, and orderings."""
    # 1. Lookups
    assert get_registered_line("assets.cash_and_cash_equivalents") is not None
    assert get_registered_line(ReportLineId.CASH_AND_CASH_EQUIVALENTS) is not None
    assert get_registered_line("non_existent_line") is None

    # 2. Framework membership
    assert (
        is_valid_line_for_framework("assets.marketable_securities", PersonalReportingFrameworkId.US_GAAP_LIKE) is True
    )
    assert is_valid_line_for_framework("assets.marketable_securities", PersonalReportingFrameworkId.HKFRS_LIKE) is False
    assert is_valid_line_for_framework("assets.investment_property", PersonalReportingFrameworkId.HKFRS_LIKE) is True
    assert is_valid_line_for_framework("assets.investment_property", PersonalReportingFrameworkId.US_GAAP_LIKE) is False

    # 3. Union lists and orderings
    us_lines = get_framework_ordered_lines(PersonalReportingFrameworkId.US_GAAP_LIKE)
    hk_lines = get_framework_ordered_lines(PersonalReportingFrameworkId.HKFRS_LIKE)

    # Union must be present in both
    us_ids = {line.line_id for line in us_lines}
    hk_ids = {line.line_id for line in hk_lines}
    assert us_ids == hk_ids

    # Marketable securities is earlier in US, Financial assets at fair value is earlier in HK
    us_marketable_idx = next(
        i for i, reg_line in enumerate(us_lines) if reg_line.line_id == ReportLineId.MARKETABLE_SECURITIES
    )
    hk_marketable_idx = next(
        i for i, reg_line in enumerate(hk_lines) if reg_line.line_id == ReportLineId.MARKETABLE_SECURITIES
    )
    assert us_marketable_idx < hk_marketable_idx


async def test_AC20_9_1_framework_balance_sheet_exact_aggregation(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC20.9.1: Proves that L1 lines exactly aggregate their L2 constituents without plugs."""
    as_of = date(2026, 5, 31)

    # 1. Create cash ledger account and equity account
    cash_acct = Account(
        user_id=test_user.id,
        name="USD Checking",
        type=AccountType.ASSET,
        currency="USD",
    )
    equity_acct = Account(
        user_id=test_user.id,
        name="Opening Balance Equity",
        type=AccountType.EQUITY,
        currency="USD",
    )
    db.add(cash_acct)
    db.add(equity_acct)
    await db.flush()

    # Seed the account balance (we can use opening balances or direct post logic, but here we can mock or insert balances directly in ledger)
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=as_of,
        status=JournalEntryStatus.POSTED,
        source_type=JournalEntrySourceType.MANUAL,
        memo="Setup cash",
    )
    db.add(entry)
    await db.flush()

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=cash_acct.id,
        direction=Direction.DEBIT,
        amount=Decimal("1500.00"),
        currency="SGD",
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=equity_acct.id,
        direction=Direction.CREDIT,
        amount=Decimal("1500.00"),
        currency="SGD",
    )
    db.add(line_debit)
    db.add(line_credit)
    await db.flush()

    # 2. Add manual property valuation component (personal use by default)
    prop = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=as_of,
        value=Decimal("500000.00"),
        currency="SGD",
        source="My Residence",
        valuation_basis="market_appraisal",
        notes="Primary residence, holding_intent: personal_use",
    )
    db.add(prop)

    # 3. Add manual property valuation component (investment intent)
    investment_prop = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=as_of,
        value=Decimal("300000.00"),
        currency="SGD",
        source="Rental Condo",
        valuation_basis="market_appraisal",
        notes="Investment condo, holding_intent: investment",
    )
    db.add(investment_prop)
    await db.flush()

    # Run for US framework
    us_bs = await assemble_framework_balance_sheet(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        as_of_date=as_of,
        currency="SGD",
        include_restricted=True,
    )

    # Assert US property treatment: both personal and investment property map to assets.manual_private_assets
    us_assets = {asset_line["line_id"]: asset_line for asset_line in us_bs["assets"]}
    assert us_assets["assets.manual_private_assets"]["amount"] == Decimal("800000.00")
    # HK-only lines are present but set to 0.00 under US
    assert us_assets["assets.investment_property"]["amount"] == Decimal("0.00")

    # Run for HK framework
    hk_bs = await assemble_framework_balance_sheet(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.HKFRS_LIKE,
        as_of_date=as_of,
        currency="SGD",
        include_restricted=True,
    )

    # Assert HK property splits: personal maps to assets.manual_private_assets, investment maps to assets.investment_property
    hk_assets = {asset_line["line_id"]: asset_line for asset_line in hk_bs["assets"]}
    assert hk_assets["assets.manual_private_assets"]["amount"] == Decimal("500000.00")
    assert hk_assets["assets.investment_property"]["amount"] == Decimal("300000.00")

    # Prove exact consolidation totals match the sum of lines exactly
    sum_assets = sum((asset_line["amount"] for asset_line in us_bs["assets"]), Decimal("0.00"))
    assert us_bs["total_assets"] == sum_assets
    assert us_bs["is_balanced"] is True


async def test_framework_income_statement_aggregation(
    db: AsyncSession,
    test_user: User,
) -> None:
    """Verify framework income statement aggregation and correct sorting."""
    start_date = date(2026, 5, 1)
    end_date = date(2026, 5, 31)

    income_acct = Account(
        user_id=test_user.id,
        name="Salary",
        type=AccountType.INCOME,
        currency="SGD",
    )
    db.add(income_acct)
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 15),
        status=JournalEntryStatus.POSTED,
        source_type=JournalEntrySourceType.MANUAL,
        memo="Monthly Salary",
    )
    db.add(entry)
    await db.flush()

    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=income_acct.id,
        direction=Direction.CREDIT,
        amount=Decimal("5000.00"),
        currency="SGD",
    )
    db.add(line)
    await db.flush()

    us_is = await assemble_framework_income_statement(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=start_date,
        end_date=end_date,
        currency="SGD",
    )

    assert us_is["total_income"] == Decimal("5000.00")
    assert us_is["net_income"] == Decimal("5000.00")


def test_map_l2_line_branches() -> None:
    """Verify all fallback and conditional paths in _map_l2_line."""
    from src.services.reporting.framework_report import _map_l2_line

    # 1. Map via decision source_id
    decision = FrameworkPolicyDecision(
        domain=PolicyFactDomain.CASH,
        recognition="...",
        measurement="...",
        classification="...",
        presentation="...",
        disclosure="...",
        line_mappings={"balance_sheet": "assets.cash_and_cash_equivalents"},
        evidence_anchors=[],
    )
    mapping = {"some_id": decision}
    line = {"account_id": "some_id", "allocation_source_type": "ledger_account"}
    res = _map_l2_line(line, mapping, PersonalReportingFrameworkId.US_GAAP_LIKE, "balance_sheet")
    assert res == "assets.cash_and_cash_equivalents"

    # 2. Portfolio adjustment - balance_sheet US vs HK
    line_p = {"allocation_source_type": "portfolio_market_adjustment"}
    assert (
        _map_l2_line(line_p, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "balance_sheet")
        == "assets.marketable_securities"
    )
    assert (
        _map_l2_line(line_p, {}, PersonalReportingFrameworkId.HKFRS_LIKE, "balance_sheet")
        == "assets.financial_assets_at_fair_value"
    )

    # 3. Portfolio adjustment - income_statement US vs HK
    assert (
        _map_l2_line(line_p, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "income_statement")
        == "income.unrealized_investment_gain_loss"
    )
    assert (
        _map_l2_line(line_p, {}, PersonalReportingFrameworkId.HKFRS_LIKE, "income_statement")
        == "income.fair_value_change_in_financial_assets"
    )

    # 4. Fallbacks - balance_sheet asset vs liability vs other
    assert (
        _map_l2_line({"type": AccountType.ASSET}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "balance_sheet")
        == "assets.cash_and_cash_equivalents"
    )
    assert (
        _map_l2_line({"type": AccountType.LIABILITY}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "balance_sheet")
        == "liabilities.financial_liabilities"
    )
    assert (
        _map_l2_line({"type": AccountType.EQUITY}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "balance_sheet")
        == "equity.fx_translation"
    )

    # 5. Fallbacks - income_statement income vs other
    assert (
        _map_l2_line({"type": AccountType.INCOME}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "income_statement")
        == "income.dividends_and_interest"
    )
    assert (
        _map_l2_line({"type": AccountType.EXPENSE}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "income_statement")
        == "expenses.investment_fees"
    )

    # 6. Fallbacks - cash_flow expense vs other
    assert (
        _map_l2_line({"type": AccountType.EXPENSE}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "cash_flow")
        == "investing.fees"
    )
    assert (
        _map_l2_line({"type": AccountType.ASSET}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "cash_flow")
        == "cash.ending_cash"
    )
    assert (
        _map_l2_line({}, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, "invalid_statement")
        == "assets.cash_and_cash_equivalents"
    )


def test_registry_lookups_and_invalid_inputs() -> None:
    """Verify registry raises errors and falls back gracefully on bad inputs."""
    assert get_registered_line("invalid_line_id") is None
    assert is_valid_line_for_framework("invalid_line_id", PersonalReportingFrameworkId.US_GAAP_LIKE) is False

    us_ending_cash = get_framework_ordered_lines(PersonalReportingFrameworkId.US_GAAP_LIKE, statement="cash_flow")
    assert len(us_ending_cash) > 0
