"""Framework policy integration for package APIs and readiness."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AssetType, AtomicPosition
from src.extraction.orm.layer3 import (
    CostBasisMethod,
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
)
from src.identity import User
from src.ledger import Account, AccountType
from src.portfolio import DividendIncome
from src.pricing import MarketDataOverride, PriceSource
from src.pricing.orm.market_data import StockPrice
from src.reporting import PERSONAL_REPORT_PACKAGE_CONTRACT
from src.reporting.extension.framework_policy import (
    _account_domain_and_instrument,
    _manual_domain_and_instrument,
    _position_domain_and_instrument,
    derive_user_framework_policy_result,
    framework_policy_facts_for_user,
)
from src.schemas.reporting import (
    PersonalReportingFrameworkId,
    PersonalReportPackageContractResponse,
    PolicyFactDomain,
)


def test_AC5_14_1_package_contract_accepts_selected_framework() -> None:
    """AC5.14.1: the embedded contract declares the selected framework vocabulary."""
    payload = dict(PERSONAL_REPORT_PACKAGE_CONTRACT)
    payload["selected_framework_id"] = PersonalReportingFrameworkId.HKFRS_LIKE.value
    response = PersonalReportPackageContractResponse.model_validate(payload)
    payload = response.model_dump(mode="json")

    assert payload["selected_framework_id"] == "personal_hkfrs_like"
    assert payload["supported_frameworks"] == ["personal_us_gaap_like", "personal_hkfrs_like"]
    assert "framework_policy_endpoint" not in payload
    assert payload["period_semantics"]["framework_id"] == "selected supported personal reporting framework"


async def test_AC20_5_1_package_policy_api_derives_framework_result_from_facts(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC20.5.1: Package policy API derives a read-only result from canonical portfolio facts."""
    report_date = date(2026, 5, 31)
    position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="HKAPI",
        broker="Framework Broker",
        quantity=Decimal("10"),
        market_value=Decimal("125.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-api-{uuid4()}",
        source_documents={"documents": [{"doc_id": "framework-broker-doc", "doc_type": "brokerage_statement"}]},
    )
    price = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="HKAPI",
        price_date=report_date,
        price=Decimal("12.50"),
        currency="SGD",
        source=PriceSource.API,
    )
    db.add_all([position, price])
    await db.flush()

    us_response = await derive_user_framework_policy_result(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=report_date,
        as_of_date=report_date,
    )
    hk_response = await derive_user_framework_policy_result(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.HKFRS_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=report_date,
        as_of_date=report_date,
    )

    assert us_response.result_id.startswith("policy-result:personal_us_gaap_like:")
    assert hk_response.result_id.startswith("policy-result:personal_hkfrs_like:")
    assert us_response.gaps == []
    assert hk_response.gaps == []
    us_line = us_response.decisions[0].line_mappings["balance_sheet"]
    hk_line = hk_response.decisions[0].line_mappings["balance_sheet"]
    assert us_line == "assets.marketable_securities"
    assert hk_line == "assets.financial_assets_at_fair_value"
    assert "atomic_position" in {anchor.anchor_type for anchor in hk_response.decisions[0].evidence_anchors}
    assert "market_price" in {anchor.anchor_type for anchor in hk_response.decisions[0].evidence_anchors}


async def test_AC20_5_1_package_policy_uses_synced_stock_prices_when_no_manual_override(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC20.5.1: Policy facts use synced StockPrice rows when no manual override exists."""
    report_date = date(2026, 5, 31)
    position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="SYNCED",
        broker="Framework Broker",
        quantity=Decimal("10"),
        market_value=Decimal("125.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-synced-{uuid4()}",
        source_documents={"documents": [{"doc_id": "synced-doc", "doc_type": "brokerage_statement"}]},
    )
    synced_price = StockPrice(
        symbol="SYNCED",
        price_date=report_date,
        price=Decimal("12.500000"),
        currency="SGD",
        source="test_provider",
    )
    db.add_all([position, synced_price])
    await db.flush()

    response = await derive_user_framework_policy_result(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=report_date,
        as_of_date=report_date,
    )

    anchors = response.decisions[0].evidence_anchors
    market_anchor = next(anchor for anchor in anchors if anchor.anchor_type == "market_price")
    assert market_anchor.source_system == "stock_price"
    assert market_anchor.source_id == str(synced_price.id)


def test_AC20_5_1_manual_valuation_components_map_to_supported_policy_instruments() -> None:
    """AC20.5.1: Manual valuation facts map to supported matrix instruments instead of policy gaps."""
    fixtures = [
        (ManualValuationComponentType.PROPERTY_VALUE, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "property"),
        (ManualValuationComponentType.CPF_BALANCE, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "manual_asset"),
        (ManualValuationComponentType.RETIREMENT_ACCOUNT, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "manual_asset"),
        (
            ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT,
            PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE,
            "manual_asset",
        ),
        (
            ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET,
            PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE,
            "manual_asset",
        ),
        (ManualValuationComponentType.LONG_TERM_SAVINGS, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "manual_asset"),
        (ManualValuationComponentType.TAX_REFUND, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "manual_asset"),
        (ManualValuationComponentType.INSURANCE_CASH_VALUE, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "manual_asset"),
        (ManualValuationComponentType.OTHER_ASSET, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "manual_asset"),
        (ManualValuationComponentType.ESOP, PolicyFactDomain.RESTRICTED_COMPENSATION, "esop"),
        (ManualValuationComponentType.RSU, PolicyFactDomain.RESTRICTED_COMPENSATION, "rsu"),
        (ManualValuationComponentType.STOCK_OPTIONS, PolicyFactDomain.RESTRICTED_COMPENSATION, "stock_option"),
        (ManualValuationComponentType.MORTGAGE_BALANCE, PolicyFactDomain.LIABILITY, "mortgage_liability"),
        (ManualValuationComponentType.TAX_PAYABLE, PolicyFactDomain.LIABILITY, "payable"),
        (ManualValuationComponentType.OTHER_LIABILITY, PolicyFactDomain.LIABILITY, "loan"),
    ]

    for component_type, expected_domain, expected_instrument in fixtures:
        snapshot = SimpleNamespace(component_type=component_type)
        assert _manual_domain_and_instrument(snapshot) == (expected_domain, expected_instrument)


def test_AC20_5_1_atomic_position_asset_types_map_to_policy_domains() -> None:
    """AC20.5.1: Atomic positions map to supported policy domains or explicit unsupported facts."""
    fixtures = [
        (AssetType.STOCK, PolicyFactDomain.LISTED_SECURITY, "listed_equity"),
        (AssetType.ETF, PolicyFactDomain.LISTED_SECURITY, "etf"),
        (AssetType.MUTUAL_FUND, PolicyFactDomain.FUND, "fund"),
        (AssetType.CASH, PolicyFactDomain.CASH, "cash"),
        (AssetType.PROPERTY, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "property"),
        (AssetType.BOND, PolicyFactDomain.LISTED_SECURITY, "bond"),
        (AssetType.OTHER, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "private_asset"),
        (None, PolicyFactDomain.UNSUPPORTED, "unknown_asset"),
    ]

    for asset_type, expected_domain, expected_instrument in fixtures:
        position = SimpleNamespace(asset_type=asset_type)
        assert _position_domain_and_instrument(position) == (expected_domain, expected_instrument)


@pytest.mark.no_db
def test_AC20_5_1_ledger_account_types_map_to_policy_domains() -> None:
    """AC20.5.1: Ledger accounts map to framework-neutral facts or stay out of policy derivation."""
    fixtures = [
        (AccountType.ASSET, (PolicyFactDomain.CASH, "bank_account")),
        (AccountType.LIABILITY, (PolicyFactDomain.LIABILITY, "loan")),
        (AccountType.INCOME, (PolicyFactDomain.DIVIDEND_INTEREST, "interest")),
        (AccountType.EXPENSE, (PolicyFactDomain.BROKERAGE_FEE, "brokerage_fee")),
        (AccountType.EQUITY, None),
    ]

    for account_type, expected in fixtures:
        account = SimpleNamespace(type=account_type)
        assert _account_domain_and_instrument(account) == expected


async def test_AC20_5_1_framework_facts_include_ledger_manual_position_and_dividend_sources(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC20.5.1: Policy facts derive from canonical sources with latest-source deduplication."""
    report_date = date(2026, 5, 31)
    account = Account(user_id=test_user.id, name="Framework Cash", type=AccountType.ASSET, currency="SGD")
    expense_account = Account(user_id=test_user.id, name="Framework Expense", type=AccountType.EXPENSE, currency="SGD")
    investment_account = Account(
        user_id=test_user.id,
        name="Framework Investment",
        type=AccountType.ASSET,
        currency="SGD",
        is_system=True,
    )
    db.add_all([account, expense_account, investment_account])
    await db.flush()

    managed_position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="DIVFACT",
        quantity=Decimal("1"),
        cost_basis=Decimal("10.00"),
        currency="SGD",
        acquisition_date=report_date,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(managed_position)
    await db.flush()

    latest_position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="DEDUP",
        broker="Framework Broker",
        quantity=Decimal("2"),
        market_value=Decimal("20.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-position-latest-{uuid4()}",
        source_documents={},
    )
    older_position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date(2026, 4, 30),
        asset_identifier="DEDUP",
        broker="Framework Broker",
        quantity=Decimal("1"),
        market_value=Decimal("10.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-position-older-{uuid4()}",
        source_documents={},
    )
    latest_manual = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.OTHER_ASSET,
        liquidity_class=ManualValuationLiquidityClass.LIQUID,
        as_of_date=report_date,
        value=Decimal("120.00"),
        currency="SGD",
        source="Other asset schedule",
    )
    older_manual = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.OTHER_ASSET,
        liquidity_class=ManualValuationLiquidityClass.LIQUID,
        as_of_date=date(2026, 4, 30),
        value=Decimal("100.00"),
        currency="SGD",
        source="Other asset schedule",
    )
    dividend = DividendIncome(
        user_id=test_user.id,
        position_id=managed_position.id,
        payment_date=report_date,
        amount=Decimal("3.50"),
        currency="SGD",
    )
    db.add_all([latest_position, older_position, latest_manual, older_manual, dividend])
    await db.flush()

    facts = await framework_policy_facts_for_user(
        db,
        test_user.id,
        report_period_start=date(2026, 5, 1),
        report_period_end=report_date,
        as_of_date=report_date,
    )

    fact_ids = {fact.fact_id for fact in facts}
    fact_by_id = {fact.fact_id: fact for fact in facts}
    assert f"account:{account.id}" in fact_ids
    assert f"account:{expense_account.id}" in fact_ids
    assert fact_by_id[f"account:{expense_account.id}"].domain == PolicyFactDomain.BROKERAGE_FEE
    assert f"atomic_position:{latest_position.id}" in fact_ids
    assert f"atomic_position:{older_position.id}" not in fact_ids
    assert f"manual_valuation_snapshot:{latest_manual.id}" in fact_ids
    assert f"manual_valuation_snapshot:{older_manual.id}" not in fact_ids
    assert f"dividend_income:{dividend.id}" in fact_ids
