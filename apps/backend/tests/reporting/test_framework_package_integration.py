"""Framework policy integration for package APIs and readiness."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import (
    CostBasisMethod,
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
)
from src.models.market_data import StockPrice
from src.models.portfolio import DividendIncome, MarketDataOverride, PriceSource
from src.models.statement import BankStatement, BankStatementStatus, Stage1Status
from src.models.user import User
from src.routers.reports import (
    personal_report_package_contract,
    personal_report_package_framework_policy,
    personal_report_package_readiness,
)
from src.schemas.reporting import (
    FrameworkPolicyDecision,
    FrameworkPolicyGap,
    FrameworkPolicyResult,
    PersonalReportingFrameworkId,
    PolicyFactDomain,
    PolicyProvenance,
    PolicyReviewState,
)
from src.services.framework_policy import (
    _account_domain_and_instrument,
    _manual_domain_and_instrument,
    _position_domain_and_instrument,
    framework_policy_facts_for_user,
)
from src.services.report_readiness import framework_policy_readiness_blockers


@pytest.mark.no_db
def test_AC5_14_1_package_contract_accepts_selected_framework_policy_endpoint() -> None:
    """AC5.14.1: Package contract consumes EPIC-020 policy result metadata, not raw market value rules."""
    response = personal_report_package_contract(framework_id=PersonalReportingFrameworkId.HKFRS_LIKE)
    payload = response.model_dump(mode="json")

    assert payload["selected_framework_id"] == "personal_hkfrs_like"
    assert payload["supported_frameworks"] == ["personal_us_gaap_like", "personal_hkfrs_like"]
    assert payload["framework_policy_endpoint"] == "/api/reports/package/framework-policy"
    assert payload["period_semantics"]["framework_id"] == "selected supported personal reporting framework"


@pytest.mark.asyncio
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

    us_response = await personal_report_package_framework_policy(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 5, 1),
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    hk_response = await personal_report_package_framework_policy(
        framework_id=PersonalReportingFrameworkId.HKFRS_LIKE,
        start_date=date(2026, 5, 1),
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
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


@pytest.mark.asyncio
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

    response = await personal_report_package_framework_policy(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 5, 1),
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )

    anchors = response.decisions[0].evidence_anchors
    market_anchor = next(anchor for anchor in anchors if anchor.anchor_type == "market_price")
    assert market_anchor.source_system == "stock_price"
    assert market_anchor.source_id == str(synced_price.id)


@pytest.mark.asyncio
async def test_AC19_7_1_readiness_consumes_framework_specific_evidence_blockers(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.7.1: Framework-selected readiness blocks policy gaps and evidence deficiencies."""
    report_date = date(2026, 5, 31)
    stale_position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="STALE",
        broker="Framework Broker",
        quantity=Decimal("5"),
        market_value=Decimal("50.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-stale-{uuid4()}",
        source_documents={"documents": [{"doc_id": "stale-doc", "doc_type": "brokerage_statement"}]},
    )
    unsupported_position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="PRIVATE-TOKEN",
        broker="Framework Broker",
        quantity=Decimal("1"),
        market_value=Decimal("500.00"),
        currency="SGD",
        asset_type=AssetType.OTHER,
        dedup_hash=f"framework-token-{uuid4()}",
        source_documents={"documents": [{"doc_id": "token-doc", "doc_type": "brokerage_statement"}]},
    )
    stale_price = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="STALE",
        price_date=date(2025, 12, 31),
        price=Decimal("10.00"),
        currency="SGD",
        source=PriceSource.MANUAL,
    )
    missing_basis = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=report_date,
        value=Decimal("500000.00"),
        currency="SGD",
        source="Manual property estimate",
        notes=None,
    )
    db.add_all([stale_position, unsupported_position, stale_price, missing_basis])
    await db.flush()

    response = await personal_report_package_readiness(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    payload = response.model_dump(mode="json")
    blockers = {blocker["code"]: blocker for blocker in payload["blockers"]}

    assert payload["state"] == "blocked"
    assert payload["source_summary"]["selected_framework_id"] == "personal_us_gaap_like"
    assert payload["source_summary"]["framework_policy_gaps"] == 1
    assert {
        "unsupported_policy_domain",
        "missing_valuation_basis",
        "stale_market_data",
    } <= set(blockers)
    assert blockers["unsupported_policy_domain"]["count"] == 1
    assert blockers["missing_valuation_basis"]["count"] == 1
    assert blockers["stale_market_data"]["count"] == 1


@pytest.mark.asyncio
async def test_AC19_7_1_readiness_uses_freshest_stock_price_or_manual_override(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.7.1: Fresh synced StockPrice rows satisfy market-data freshness without manual overrides."""
    report_date = date(2026, 5, 31)
    position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="FRESH",
        broker="Framework Broker",
        quantity=Decimal("5"),
        market_value=Decimal("50.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-fresh-{uuid4()}",
        source_documents={"documents": [{"doc_id": "fresh-doc", "doc_type": "brokerage_statement"}]},
    )
    stale_override = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="FRESH",
        price_date=date(2025, 12, 31),
        price=Decimal("9.00"),
        currency="SGD",
        source=PriceSource.MANUAL,
    )
    fresh_synced_price = StockPrice(
        symbol="FRESH",
        price_date=report_date,
        price=Decimal("10.000000"),
        currency="SGD",
        source="test_provider",
    )
    db.add_all([position, stale_override, fresh_synced_price])
    await db.flush()

    response = await personal_report_package_readiness(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    blockers = {blocker.code: blocker for blocker in response.blockers}

    assert "stale_market_data" not in blockers


@pytest.mark.asyncio
async def test_AC19_7_1_readiness_deduplicates_normalized_market_data_symbols(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.7.1: Normalized holdings dedupe while blank identifiers still block readiness."""
    report_date = date(2026, 5, 31)
    upper_position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="DUPCASE",
        broker="Framework Broker",
        quantity=Decimal("5"),
        market_value=Decimal("50.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-dup-upper-{uuid4()}",
        source_documents={"documents": [{"doc_id": "dup-upper-doc", "doc_type": "brokerage_statement"}]},
    )
    lower_position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="dupcase",
        broker="Framework Broker",
        quantity=Decimal("5"),
        market_value=Decimal("50.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-dup-lower-{uuid4()}",
        source_documents={"documents": [{"doc_id": "dup-lower-doc", "doc_type": "brokerage_statement"}]},
    )
    blank_position = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="   ",
        broker="Framework Broker",
        quantity=Decimal("5"),
        market_value=Decimal("50.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"framework-blank-{uuid4()}",
        source_documents={"documents": [{"doc_id": "blank-doc", "doc_type": "brokerage_statement"}]},
    )
    db.add_all([upper_position, lower_position, blank_position])
    await db.flush()

    response = await personal_report_package_readiness(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    blockers = {blocker.code: blocker for blocker in response.blockers}

    assert "stale_market_data" in blockers
    assert blockers["stale_market_data"].count == 2


@pytest.mark.no_db
def test_AC20_6_1_ai_suggestions_require_reviewed_policy_fields_for_readiness() -> None:
    """AC20.6.1: AI suggestions and incomplete policy fields become readiness blocker codes."""
    decision = FrameworkPolicyDecision.model_construct(
        domain=PolicyFactDomain.LISTED_SECURITY,
        recognition="Recognize listed holding from broker evidence.",
        measurement="AI-proposed fair-value measurement.",
        classification="Marketable investment asset.",
        presentation="Balance sheet investment line.",
        disclosure=None,
        line_mappings={"balance_sheet": "assets.marketable_securities"},
        evidence_anchors=[],
        provenance=PolicyProvenance.REVIEWED_AI_SUGGESTION,
        confidence_tier="MEDIUM",
        review_state=PolicyReviewState.PENDING_REVIEW,
        policy_field_name="measurement_basis",
        accepted_value=None,
    )
    policy_result = FrameworkPolicyResult.model_construct(
        result_id="policy-result:ai-pending",
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        generated_at=date(2026, 5, 31),
        required_statements=["balance_sheet"],
        decisions=[decision],
        gaps=[],
    )

    blockers = framework_policy_readiness_blockers(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        policy_result=policy_result,
        report_input_count=1,
        missing_valuation_basis_count=0,
        stale_market_data_count=0,
    )
    blocker_codes = {blocker["code"] for blocker in blockers}

    assert "framework_policy_missing_dimensions" in blocker_codes
    assert "framework_ai_suggestion_unreviewed" in blocker_codes


@pytest.mark.no_db
def test_AC19_7_1_selected_framework_requires_non_empty_policy_result() -> None:
    """AC19.7.1: Selected-framework readiness fails closed when no policy result can be derived."""
    empty_policy_result = FrameworkPolicyResult.model_construct(
        result_id="policy-result:empty",
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        generated_at=date(2026, 5, 31),
        required_statements=["balance_sheet"],
        decisions=[],
        gaps=[],
    )

    blockers = framework_policy_readiness_blockers(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        policy_result=empty_policy_result,
        report_input_count=1,
        missing_valuation_basis_count=0,
        stale_market_data_count=0,
    )

    assert {blocker["code"] for blocker in blockers} == {"missing_framework_policy_result"}


@pytest.mark.asyncio
async def test_AC19_7_1_statement_only_inputs_do_not_require_framework_policy_result(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.7.1: Statement-only package inputs do not require an empty framework policy result."""
    report_date = date(2026, 5, 31)
    statement = BankStatement(
        user_id=test_user.id,
        file_path=f"s3://test/{uuid4()}.csv",
        file_hash=uuid4().hex,
        original_filename=f"{uuid4()}.csv",
        institution="Framework Bank",
        period_start=date(2026, 5, 1),
        period_end=report_date,
        status=BankStatementStatus.APPROVED,
        balance_validated=True,
        validation_error=None,
        stage1_status=Stage1Status.APPROVED,
    )
    db.add(statement)
    await db.flush()

    response = await personal_report_package_readiness(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    blocker_codes = {blocker.code for blocker in response.blockers}

    assert response.source_summary["statements"] == 1
    assert "missing_framework_policy_result" not in blocker_codes


@pytest.mark.no_db
def test_AC20_5_1_manual_valuation_components_map_to_supported_policy_instruments() -> None:
    """AC20.5.1: Manual valuation facts map to supported matrix instruments instead of policy gaps."""
    fixtures = [
        (ManualValuationComponentType.PROPERTY_VALUE, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "property"),
        (ManualValuationComponentType.CPF_BALANCE, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "manual_asset"),
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


@pytest.mark.no_db
def test_AC20_5_1_atomic_position_asset_types_map_to_policy_domains() -> None:
    """AC20.5.1: Atomic positions map to supported policy domains or explicit unsupported facts."""
    fixtures = [
        (AssetType.STOCK, PolicyFactDomain.LISTED_SECURITY, "listed_equity"),
        (AssetType.ETF, PolicyFactDomain.LISTED_SECURITY, "etf"),
        (AssetType.MUTUAL_FUND, PolicyFactDomain.FUND, "fund"),
        (AssetType.CASH, PolicyFactDomain.CASH, "cash"),
        (AssetType.PROPERTY, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "property"),
        (AssetType.BOND, PolicyFactDomain.UNSUPPORTED, "bond"),
        (AssetType.OTHER, PolicyFactDomain.UNSUPPORTED, "other"),
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
        (AccountType.EXPENSE, None),
        (AccountType.EQUITY, None),
    ]

    for account_type, expected in fixtures:
        account = SimpleNamespace(type=account_type)
        assert _account_domain_and_instrument(account) == expected


@pytest.mark.asyncio
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
    assert f"account:{account.id}" in fact_ids
    assert f"account:{expense_account.id}" not in fact_ids
    assert f"atomic_position:{latest_position.id}" in fact_ids
    assert f"atomic_position:{older_position.id}" not in fact_ids
    assert f"manual_valuation_snapshot:{latest_manual.id}" in fact_ids
    assert f"manual_valuation_snapshot:{older_manual.id}" not in fact_ids
    assert f"dividend_income:{dividend.id}" in fact_ids


@pytest.mark.no_db
def test_AC19_7_1_framework_policy_helper_emits_all_evidence_blocker_codes() -> None:
    """AC19.7.1: Readiness helper emits framework, policy gap, valuation, and market-data blockers."""
    policy_result = FrameworkPolicyResult.model_construct(
        result_id="policy-result:gap",
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        generated_at=date(2026, 5, 31),
        required_statements=["balance_sheet"],
        decisions=[
            FrameworkPolicyDecision(
                domain=PolicyFactDomain.CASH,
                recognition="Recognize cash from reviewed source evidence.",
                measurement="Measure cash at nominal amount.",
                classification="Cash asset.",
                presentation="Balance sheet cash.",
                disclosure="Disclose source coverage.",
                line_mappings={"balance_sheet": "assets.cash"},
            )
        ],
        gaps=[
            FrameworkPolicyGap(
                code="unsupported_policy_domain",
                fact_id="fact-private-token",
                domain=PolicyFactDomain.UNSUPPORTED,
                instrument_type="other",
                blocker=True,
                reason="Unsupported.",
                remediation="Review policy rule.",
                evidence_anchors=[],
            )
        ],
    )

    blockers = framework_policy_readiness_blockers(
        framework_id=PersonalReportingFrameworkId.HKFRS_LIKE,
        policy_result=policy_result,
        report_input_count=1,
        missing_valuation_basis_count=2,
        stale_market_data_count=3,
    )
    blocker_codes = {blocker["code"] for blocker in blockers}

    assert {
        "missing_framework_policy_result",
        "unsupported_policy_domain",
        "missing_valuation_basis",
        "stale_market_data",
    } <= blocker_codes
    framework_blockers = [
        blocker
        for blocker in blockers
        if blocker["code"]
        in {
            "missing_framework_policy_result",
            "unsupported_policy_domain",
            "framework_policy_missing_dimensions",
        }
    ]
    assert framework_blockers
    assert {blocker["action_href"] for blocker in framework_blockers} == {"/reports/package"}
    assert {
        blocker["code"]
        for blocker in framework_policy_readiness_blockers(
            framework_id="personal_cn_cas_like",
            policy_result=None,
            report_input_count=1,
            missing_valuation_basis_count=0,
            stale_market_data_count=0,
        )
    } == {"unsupported_framework"}
