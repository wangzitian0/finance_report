"""Framework policy integration for package APIs and readiness."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.models.portfolio import MarketDataOverride, PriceSource
from src.models.user import User
from src.routers.reports import (
    personal_report_package_contract,
    personal_report_package_framework_policy,
    personal_report_package_readiness,
)
from src.schemas.reporting import (
    FrameworkPolicyDecision,
    FrameworkPolicyResult,
    PersonalReportingFrameworkId,
    PolicyFactDomain,
    PolicyProvenance,
    PolicyReviewState,
)
from src.services.report_readiness import framework_policy_readiness_blockers


@pytest.fixture(autouse=True)
def patch_database_connection():
    """Pure contract tests in this module do not require an implicit database."""
    yield


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
