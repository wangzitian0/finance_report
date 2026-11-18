from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AssetType, AtomicPosition
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.identity import User
from src.ledger import AccountType
from src.portfolio import DividendIncome
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass, MarketDataOverride, PriceSource
from src.pricing.orm.market_data import StockPrice
from src.reporting import PERSONAL_REPORT_PACKAGE_CONTRACT
from src.reporting.extension.framework_policy import (
    _account_domain_and_instrument,
    _manual_domain_and_instrument,
    _position_domain_and_instrument,
    derive_user_framework_policy_result,
    framework_policy_facts_for_user,
)
from src.schemas.reporting import PersonalReportingFrameworkId, PersonalReportPackageContractResponse, PolicyFactDomain
from tests.reporting._report_fixtures import seed_accounts, seed_valuations


@pytest.mark.no_db
def test_AC5_14_1_and_AC20_5_1_contract_and_domain_mappings() -> None:
    payload = dict(PERSONAL_REPORT_PACKAGE_CONTRACT) | {
        "selected_framework_id": PersonalReportingFrameworkId.HKFRS_LIKE.value
    }
    dumped = PersonalReportPackageContractResponse.model_validate(payload).model_dump(mode="json")
    assert dumped["selected_framework_id"] == "personal_hkfrs_like" and dumped["supported_frameworks"] == [
        "personal_us_gaap_like",
        "personal_hkfrs_like",
    ]
    assert (
        "framework_policy_endpoint" not in dumped
        and dumped["period_semantics"]["framework_id"] == "selected supported personal reporting framework"
    )

    for comp, exp_dom, exp_inst in (
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
    ):
        assert _manual_domain_and_instrument(SimpleNamespace(component_type=comp)) == (exp_dom, exp_inst)

    for asset_t, exp_dom, exp_inst in (
        (AssetType.STOCK, PolicyFactDomain.LISTED_SECURITY, "listed_equity"),
        (AssetType.ETF, PolicyFactDomain.LISTED_SECURITY, "etf"),
        (AssetType.MUTUAL_FUND, PolicyFactDomain.FUND, "fund"),
        (AssetType.CASH, PolicyFactDomain.CASH, "cash"),
        (AssetType.PROPERTY, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "property"),
        (AssetType.BOND, PolicyFactDomain.LISTED_SECURITY, "bond"),
        (AssetType.OTHER, PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE, "private_asset"),
        (None, PolicyFactDomain.UNSUPPORTED, "unknown_asset"),
    ):
        assert _position_domain_and_instrument(SimpleNamespace(asset_type=asset_t)) == (exp_dom, exp_inst)

    for acct_t, exp in (
        (AccountType.ASSET, (PolicyFactDomain.CASH, "bank_account")),
        (AccountType.LIABILITY, (PolicyFactDomain.LIABILITY, "loan")),
        (AccountType.INCOME, (PolicyFactDomain.PERSONAL_INCOME, "unclassified_income")),
        (AccountType.EXPENSE, (PolicyFactDomain.PERSONAL_EXPENSE, "unclassified_expense")),
        (AccountType.EQUITY, None),
    ):
        assert _account_domain_and_instrument(SimpleNamespace(type=acct_t)) == exp


async def test_AC20_5_1_package_policy_api_and_market_price_sources(db: AsyncSession, test_user: User) -> None:
    rep_date = date(2026, 5, 31)
    pos1 = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=rep_date,
        asset_identifier="HKAPI",
        broker="Broker",
        quantity=Decimal("10"),
        market_value=Decimal("125.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"fw-api-{uuid4()}",
        source_documents={"documents": [{"doc_id": "d1", "doc_type": "brokerage_statement"}]},
    )
    pos2 = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=rep_date,
        asset_identifier="SYNCED",
        broker="Broker",
        quantity=Decimal("10"),
        market_value=Decimal("125.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"fw-sync-{uuid4()}",
        source_documents={"documents": [{"doc_id": "d2", "doc_type": "brokerage_statement"}]},
    )
    override = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="HKAPI",
        price_date=rep_date,
        price=Decimal("12.50"),
        currency="SGD",
        source=PriceSource.API,
    )
    synced = StockPrice(
        symbol="SYNCED", price_date=rep_date, price=Decimal("12.500000"), currency="SGD", source="test_provider"
    )
    db.add_all([pos1, pos2, override, synced])
    await db.flush()
    us_res = await derive_user_framework_policy_result(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=rep_date,
        as_of_date=rep_date,
    )
    hk_res = await derive_user_framework_policy_result(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.HKFRS_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=rep_date,
        as_of_date=rep_date,
    )
    assert us_res.result_id.startswith("policy-result:personal_us_gaap_like:") and hk_res.result_id.startswith(
        "policy-result:personal_hkfrs_like:"
    )
    assert us_res.gaps == hk_res.gaps == []
    assert us_res.decisions[0].line_mappings["balance_sheet"] == "assets.marketable_securities"
    assert hk_res.decisions[0].line_mappings["balance_sheet"] == "assets.financial_assets_at_fair_value"
    assert {"atomic_position", "market_price"} <= {a.anchor_type for a in hk_res.decisions[0].evidence_anchors}
    assert any(
        a.anchor_type == "market_price" and a.source_system == "stock_price" and a.source_id == str(synced.id)
        for d in us_res.decisions
        for a in d.evidence_anchors
    )


async def test_AC20_5_1_framework_facts_include_ledger_manual_position_and_dividend_sources(
    db: AsyncSession, test_user: User
) -> None:
    rep_date = date(2026, 5, 31)
    account, expense, inv = await seed_accounts(
        db,
        test_user.id,
        ("Cash", AccountType.ASSET),
        ("Expense", AccountType.EXPENSE),
        ("Investment", AccountType.ASSET, "SGD", {"is_system": True}),
    )
    mp = ManagedPosition(
        user_id=test_user.id,
        account_id=inv.id,
        asset_identifier="DIVFACT",
        quantity=Decimal("1"),
        cost_basis=Decimal("10.00"),
        currency="SGD",
        acquisition_date=rep_date,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(mp)
    await db.flush()
    latest_pos = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=rep_date,
        asset_identifier="DEDUP",
        broker="Broker",
        quantity=Decimal("2"),
        market_value=Decimal("20.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"fw-lat-{uuid4()}",
        source_documents={},
    )
    older_pos = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date(2026, 4, 30),
        asset_identifier="DEDUP",
        broker="Broker",
        quantity=Decimal("1"),
        market_value=Decimal("10.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"fw-old-{uuid4()}",
        source_documents={},
    )
    db.add_all(
        [
            latest_pos,
            older_pos,
            DividendIncome(
                user_id=test_user.id, position_id=mp.id, payment_date=rep_date, amount=Decimal("3.50"), currency="SGD"
            ),
        ]
    )
    lat_m, old_m = await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.OTHER_ASSET,
            ManualValuationLiquidityClass.LIQUID,
            "120.00",
            "SGD",
            rep_date,
            "Other asset",
        ),
        (
            ManualValuationComponentType.OTHER_ASSET,
            ManualValuationLiquidityClass.LIQUID,
            "100.00",
            "SGD",
            date(2026, 4, 30),
            "Other asset",
        ),
    )
    div = (
        await db.execute(__import__("sqlalchemy").select(DividendIncome).where(DividendIncome.position_id == mp.id))
    ).scalar_one()
    facts = {
        f.fact_id: f
        for f in await framework_policy_facts_for_user(
            db, test_user.id, report_period_start=date(2026, 5, 1), report_period_end=rep_date, as_of_date=rep_date
        )
    }
    assert {
        f"account:{account.id}",
        f"account:{expense.id}",
        f"atomic_position:{latest_pos.id}",
        f"manual_valuation_snapshot:{lat_m.id}",
        f"dividend_income:{div.id}",
    } <= set(facts)
    assert f"atomic_position:{older_pos.id}" not in facts and f"manual_valuation_snapshot:{old_m.id}" not in facts
    assert facts[f"account:{expense.id}"].domain == PolicyFactDomain.PERSONAL_EXPENSE
