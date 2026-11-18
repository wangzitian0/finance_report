from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AssetType, AtomicPosition
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.identity import User
from src.ledger import AccountType
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass
from src.reporting.base.l1_registry import get_framework_ordered_lines, get_registered_line, is_valid_line_for_framework
from src.reporting.extension.framework_report import (
    _map_l2_line,
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.reporting.extension.reporting_calc import ReportError
from src.schemas.reporting import FrameworkPolicyDecision, PersonalReportingFrameworkId, PolicyFactDomain, ReportLineId
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_valuations


@pytest.mark.no_db
def test_l1_registry_lookup_and_validation() -> None:
    assert get_registered_line("assets.cash_and_cash_equivalents") is not None
    assert get_registered_line(ReportLineId.CASH_AND_CASH_EQUIVALENTS) is not None
    assert get_registered_line("non_existent_line") is None and get_registered_line("invalid_line_id") is None
    assert (
        is_valid_line_for_framework("assets.marketable_securities", PersonalReportingFrameworkId.US_GAAP_LIKE) is True
    )
    assert is_valid_line_for_framework("assets.marketable_securities", PersonalReportingFrameworkId.HKFRS_LIKE) is False
    assert is_valid_line_for_framework("assets.investment_property", PersonalReportingFrameworkId.HKFRS_LIKE) is True
    assert is_valid_line_for_framework("assets.investment_property", PersonalReportingFrameworkId.US_GAAP_LIKE) is False
    assert is_valid_line_for_framework("invalid_line_id", PersonalReportingFrameworkId.US_GAAP_LIKE) is False
    us_lines = get_framework_ordered_lines(PersonalReportingFrameworkId.US_GAAP_LIKE)
    hk_lines = get_framework_ordered_lines(PersonalReportingFrameworkId.HKFRS_LIKE)
    assert {line.line_id for line in us_lines} == {line.line_id for line in hk_lines}
    assert next(i for i, line in enumerate(us_lines) if line.line_id == ReportLineId.MARKETABLE_SECURITIES) < next(
        i for i, line in enumerate(hk_lines) if line.line_id == ReportLineId.MARKETABLE_SECURITIES
    )
    assert len(get_framework_ordered_lines(PersonalReportingFrameworkId.US_GAAP_LIKE, statement="cash_flow")) > 0


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("line", "framework", "stmt", "expected"),
    [
        (
            {"account_id": "some_id", "allocation_source_type": "ledger_account"},
            PersonalReportingFrameworkId.US_GAAP_LIKE,
            "balance_sheet",
            "assets.cash_and_cash_equivalents",
        ),
        (
            {"allocation_source_type": "portfolio_market_adjustment"},
            PersonalReportingFrameworkId.US_GAAP_LIKE,
            "balance_sheet",
            "assets.marketable_securities",
        ),
        (
            {"allocation_source_type": "portfolio_market_adjustment"},
            PersonalReportingFrameworkId.HKFRS_LIKE,
            "balance_sheet",
            "assets.financial_assets_at_fair_value",
        ),
        (
            {"allocation_source_type": "portfolio_market_adjustment"},
            PersonalReportingFrameworkId.US_GAAP_LIKE,
            "income_statement",
            "income.unrealized_investment_gain_loss",
        ),
        (
            {"allocation_source_type": "portfolio_market_adjustment"},
            PersonalReportingFrameworkId.HKFRS_LIKE,
            "income_statement",
            "income.fair_value_change_in_financial_assets",
        ),
        (
            {"allocation_source_type": "portfolio_cost_basis"},
            PersonalReportingFrameworkId.US_GAAP_LIKE,
            "balance_sheet",
            "assets.marketable_securities",
        ),
        (
            {"type": AccountType.EQUITY},
            PersonalReportingFrameworkId.US_GAAP_LIKE,
            "balance_sheet",
            "equity.fx_translation",
        ),
    ],
)
def test_map_l2_line_branches(line: dict, framework: PersonalReportingFrameworkId, stmt: str, expected: str) -> None:
    dec = FrameworkPolicyDecision(
        domain=PolicyFactDomain.CASH,
        recognition=".",
        measurement=".",
        classification=".",
        presentation=".",
        disclosure=".",
        line_mappings={"balance_sheet": "assets.cash_and_cash_equivalents"},
        evidence_anchors=[],
    )
    assert _map_l2_line(line, {"some_id": dec}, framework, stmt) == expected


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("line", "stmt", "match"),
    [
        ({"type": AccountType.ASSET}, "balance_sheet", "No registered L1 mapping"),
        ({}, "invalid_statement", "Unsupported framework report statement"),
    ],
)
def test_map_l2_line_errors(line: dict, stmt: str, match: str) -> None:
    with pytest.raises(ReportError, match=match):
        _map_l2_line(line, {}, PersonalReportingFrameworkId.US_GAAP_LIKE, stmt)


async def test_AC20_9_1_framework_balance_sheet_and_income_aggregation(db: AsyncSession, test_user: User) -> None:
    as_of = date(2026, 5, 31)
    cash, equity, salary, brokerage = await seed_accounts(
        db,
        test_user.id,
        ("USD Checking", AccountType.ASSET, "USD"),
        ("Opening Balance Equity", AccountType.EQUITY, "USD"),
        ("Salary", AccountType.INCOME, "SGD"),
        ("Brokerage", AccountType.ASSET, "SGD"),
    )
    await post_pair(db, test_user.id, as_of, "Setup cash", cash, equity, "1500.00", currency="SGD")
    await post_pair(db, test_user.id, date(2026, 5, 15), "Salary", cash, salary, "5000.00", currency="SGD")
    await post_pair(db, test_user.id, as_of, "Brokerage", brokerage, equity, "1200.00", currency="SGD")
    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            "500000.00",
            "SGD",
            as_of,
            "My Residence",
            {"valuation_basis": "market_appraisal", "notes": "Primary residence, holding_intent: personal_use"},
        ),
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            "300000.00",
            "SGD",
            as_of,
            "Rental Condo",
            {"valuation_basis": "market_appraisal", "notes": "Investment condo, holding_intent: investment"},
        ),
    )
    db.add_all(
        [
            ManagedPosition(
                user_id=test_user.id,
                account_id=brokerage.id,
                asset_identifier="NVDA",
                quantity=Decimal("10"),
                cost_basis=Decimal("1000.00"),
                currency="SGD",
                acquisition_date=as_of,
                status=PositionStatus.ACTIVE,
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=as_of,
                asset_identifier="NVDA",
                broker=brokerage.name,
                quantity=Decimal("10"),
                market_value=Decimal("1500.00"),
                currency="SGD",
                asset_type=AssetType.STOCK,
                dedup_hash=f"l1-{uuid4().hex}",
                source_documents={},
            ),
        ]
    )
    await db.flush()
    us_is = await assemble_framework_income_statement(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 5, 1),
        end_date=as_of,
        currency="SGD",
        base_currency="SGD",
    )
    assert (us_is["total_income"], us_is["net_income"]) == (Decimal("5000.00"), Decimal("5000.00"))
    us_bs = await assemble_framework_balance_sheet(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        as_of_date=as_of,
        currency="SGD",
        include_restricted=True,
        base_currency="SGD",
    )
    hk_bs = await assemble_framework_balance_sheet(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.HKFRS_LIKE,
        as_of_date=as_of,
        currency="SGD",
        include_restricted=True,
        base_currency="SGD",
    )
    us_a = {a["line_id"]: a["amount"] for a in us_bs["assets"]}
    hk_a = {a["line_id"]: a["amount"] for a in hk_bs["assets"]}
    assert (
        us_a["assets.manual_private_assets"],
        us_a["assets.investment_property"],
        hk_a["assets.manual_private_assets"],
        hk_a["assets.investment_property"],
    ) == (Decimal("800000.00"), Decimal("0.00"), Decimal("500000.00"), Decimal("300000.00"))
    assert (
        us_a["assets.marketable_securities"],
        hk_a["assets.financial_assets_at_fair_value"],
        us_a["assets.cash_and_cash_equivalents"],
        hk_a["assets.cash_and_cash_equivalents"],
    ) == (Decimal("1500.00"), Decimal("1500.00"), Decimal("6700.00"), Decimal("6700.00"))
    assert us_bs["total_assets"] == sum(us_a.values(), Decimal("0.00")) and us_bs["is_balanced"] is True
