from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.orm.layer2 import AssetType, AtomicPosition, AtomicTransaction
from src.extraction.orm.layer3 import (
    ClassificationRule,
    TransactionClassification,
)
from src.portfolio.orm.portfolio import (
    CostBasisMethod,
    ManagedPosition,
    PositionStatus,
)
from src.ledger import Account, AccountType
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass, ValuationService
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_income_statement,
    get_net_worth_allocation_schedule,
)
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_valuations


def _pos_snap(
    db: AsyncSession,
    user_id,
    account: Account,
    *,
    ticker: str,
    qty: str,
    cost: str,
    mv: str | None,
    as_of: date,
    ccy: str = "SGD",
) -> None:
    db.add(
        ManagedPosition(
            user_id=user_id,
            account_id=account.id,
            asset_identifier=ticker,
            quantity=Decimal(qty),
            cost_basis=Decimal(cost),
            currency=ccy,
            acquisition_date=as_of,
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    if mv is not None:
        db.add(
            AtomicPosition(
                user_id=user_id,
                snapshot_date=as_of,
                asset_identifier=ticker,
                broker=account.name,
                quantity=Decimal(qty),
                market_value=Decimal(mv),
                currency=ccy,
                asset_type=AssetType.STOCK,
                sector="Technology",
                geography="US",
                dedup_hash=f"position-{uuid4().hex}",
                source_documents={},
            )
        )


@pytest.mark.parametrize(
    ("cost_entry", "neg_bank", "ticker", "cost", "mv", "future_days", "expected_assets", "expected_adj", "expect_line"),
    [
        ("1000.00", False, "AAPL", "1000.00", "1500.00", False, Decimal("1500.00"), Decimal("500.00"), True),
        (None, False, "TSLA", "0.00", "1250.00", False, Decimal("1250.00"), Decimal("1250.00"), True),
        (None, False, "FULLERTON_SGD_MMF", "0.00", "1234.00", True, Decimal("1234.00"), Decimal("1234.00"), True),
        (None, True, "FULLERTON_SGD_MMF", "0.00", "1250.50", False, Decimal("671.72"), Decimal("1250.50"), True),
        ("1200.00", False, "NVDA", "1000.00", "1500.00", False, Decimal("1700.00"), Decimal("500.00"), True),
        (None, False, "MISSING", "1000.00", None, False, Decimal("0.00"), Decimal("0.00"), False),
        ("1000.00", False, "MSFT", "1000.00", "1000.00", False, Decimal("1000.00"), Decimal("0.00"), False),
    ],
)
async def test_portfolio_market_value_balance_sheet_cases(
    db: AsyncSession,
    test_user,
    cost_entry: str | None,
    neg_bank: bool,
    ticker: str,
    cost: str,
    mv: str | None,
    future_days: bool,
    expected_assets: Decimal,
    expected_adj: Decimal,
    expect_line: bool,
) -> None:
    report_date = date.today() if future_days else date(2025, 3, 31)
    snap_date = (
        (
            date(report_date.year + 1, 1, 31)
            if report_date.month == 12
            else date(report_date.year, report_date.month + 1, 1)
        )
        if future_days
        else report_date
    )
    broker, equity, bank = await seed_accounts(
        db,
        test_user.id,
        ("Moomoo", AccountType.ASSET),
        ("Owner Equity", AccountType.EQUITY),
        ("Bank - Main", AccountType.ASSET),
    )
    if cost_entry:
        await post_pair(db, test_user.id, report_date, "Cost", broker, equity, cost_entry)
    if neg_bank:
        await post_pair(db, test_user.id, report_date, "Neg", equity, bank, "578.78")
    _pos_snap(db, test_user.id, broker, ticker=ticker, qty="10", cost=cost, mv=mv, as_of=snap_date)
    await db.commit()
    rep = await generate_balance_sheet(db, test_user.id, as_of_date=report_date, currency="SGD")
    assert (rep["total_assets"], rep["net_worth_adjustment_gain_loss"]) == (expected_assets, expected_adj)
    assert any("market valuation adjustment" in line["name"].lower() for line in rep["assets"]) is expect_line


async def test_portfolio_currency_conversion_and_missing_fx_errors(db: AsyncSession, test_user) -> None:
    acq, rep_date = date(2025, 1, 15), date(2025, 3, 31)
    [broker] = await seed_accounts(db, test_user.id, ("Moomoo USD", AccountType.ASSET))
    _pos_snap(
        db, test_user.id, broker, ticker="META", qty="10", cost="1000.00", mv="1500.00", as_of=rep_date, ccy="USD"
    )
    await db.commit()
    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD")

    db.add_all(
        [
            FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=acq, source="test"),
            FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=rep_date, source="test"),
        ]
    )
    await db.commit()
    rep = await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD")
    assert rep["total_assets"] == Decimal("2025.00") and any(
        line["amount"] == Decimal("2025.00") for line in rep["assets"]
    )

    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.RSU,
            ManualValuationLiquidityClass.RESTRICTED,
            "1000.00",
            "EUR",
            rep_date,
            "Employer RSU",
        ),
        commit=True,
    )
    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD")


async def test_balance_sheet_restricted_exclusion_and_valuation_gap_warning(db: AsyncSession, test_user) -> None:
    rep_date = date(2025, 3, 31)
    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            "1200000.00",
            "SGD",
            rep_date,
            "Singapore Condo",
        ),
        (
            ManualValuationComponentType.ESOP,
            ManualValuationLiquidityClass.RESTRICTED,
            "42000.00",
            "SGD",
            rep_date,
            "Employer ESOP",
        ),
        (
            ManualValuationComponentType.TAX_REFUND,
            ManualValuationLiquidityClass.LIQUID,
            "1200.00",
            "SGD",
            rep_date,
            "IRAS refund",
        ),
        (
            ManualValuationComponentType.MORTGAGE_BALANCE,
            ManualValuationLiquidityClass.LIABILITY,
            "600000.00",
            "SGD",
            rep_date,
            "Singapore Condo Mortgage",
        ),
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            "500000.00",
            "SGD",
            date(2025, 6, 30),
            "Future Condo",
        ),
        commit=True,
    )
    liq = await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD", include_restricted=False)
    full = await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD", include_restricted=True)
    assert (
        liq["total_assets"],
        liq["total_liabilities"],
        full["total_assets"],
        full["total_liabilities"],
        full["excluded_holdings"],
    ) == (Decimal("1200.00"), Decimal("0.00"), Decimal("1243200.00"), Decimal("600000.00"), [])
    assert liq["excluded_holdings"] == [
        {
            "asset_class": "real_estate",
            "total_assets": Decimal("1200000.00"),
            "total_liabilities": Decimal("600000.00"),
            "net_worth": Decimal("600000.00"),
            "warnings": [],
        },
        {
            "asset_class": "restricted_comp",
            "total_assets": Decimal("42000.00"),
            "total_liabilities": Decimal("0.00"),
            "net_worth": Decimal("42000.00"),
            "warnings": [],
        },
    ]

    early = await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert early["total_assets"] == 0 and any(
        w["type"] == "valuation_component_not_yet_recorded"
        and w["source"] == "Singapore Condo"
        and w["earliest_as_of_date"] == "2025-03-31"
        for w in early["portfolio_warnings"]
    )


async def test_AC11_20_retirement_and_benefit_assets_and_AC17_14_2_allocation(db: AsyncSession, test_user) -> None:
    rep_date, svc = date(2026, 6, 18), ValuationService()
    snaps = [
        await svc.create_valuation_snapshot(
            db, test_user.id, component_type=ct, as_of_date=rep_date, value=Decimal(v), currency="SGD", source=s
        )
        for ct, s, v in (
            (ManualValuationComponentType.RETIREMENT_ACCOUNT, "401k", "100000.00"),
            (ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT, "SS", "12000.00"),
            (ManualValuationComponentType.CPF_BALANCE, "CPF", "50000.00"),
            (ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET, "SRP", "15000.00"),
            (ManualValuationComponentType.INSURANCE_CASH_VALUE, "Ins", "8000.00"),
        )
    ]
    await db.commit()
    assert {s.liquidity_class for s in snaps} == {ManualValuationLiquidityClass.RESTRICTED}
    assert (
        await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD", include_restricted=False)
    )["total_assets"] == Decimal("0.00")
    full = await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD", include_restricted=True)
    assert (full["total_assets"], full["net_worth_adjustment_gain_loss"]) == (
        Decimal("185000.00"),
        Decimal("185000.00"),
    )
    sched = await get_net_worth_allocation_schedule(
        db, test_user.id, as_of_date=rep_date, currency="SGD", include_restricted=True
    )
    r = {(row["asset_class"], row["liquidity_class"], row["source_currency"]): row for row in sched["rows"]}[
        "retirement_and_benefit_assets", "restricted", "SGD"
    ]
    assert (
        sched["total_assets"],
        sched["net_worth"],
        r["value"],
        r["percentage_of_net_worth"],
        r["source_line_count"],
    ) == (Decimal("185000.00"), Decimal("185000.00"), Decimal("185000.00"), Decimal("100.00"), 5)

    r_date = date(2025, 3, 31)
    bank, broker, equity = await seed_accounts(
        db,
        test_user.id,
        ("Main Bank", AccountType.ASSET),
        ("Moomoo", AccountType.ASSET),
        ("Owner Equity", AccountType.EQUITY),
    )
    db.add(FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=r_date, source="test"))
    await post_pair(db, test_user.id, r_date, "Bank", bank, equity, "5000.00")
    await post_pair(db, test_user.id, r_date, "Broker", broker, equity, "1200.00")
    _pos_snap(db, test_user.id, broker, ticker="AAPL", qty="10", cost="1000.00", mv="1500.00", as_of=r_date)
    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            "10000.00",
            "SGD",
            r_date,
            "Condo",
        ),
        (
            ManualValuationComponentType.MORTGAGE_BALANCE,
            ManualValuationLiquidityClass.LIABILITY,
            "4000.00",
            "SGD",
            r_date,
            "Mortgage",
        ),
        (ManualValuationComponentType.RSU, ManualValuationLiquidityClass.RESTRICTED, "1000.00", "USD", r_date, "RSU"),
        commit=True,
    )
    alloc = await get_net_worth_allocation_schedule(
        db, test_user.id, as_of_date=r_date, currency="SGD", include_restricted=True
    )
    rows = {(row["asset_class"], row["liquidity_class"], row["source_currency"]): row for row in alloc["rows"]}
    assert (alloc["total_assets"], alloc["total_liabilities"], alloc["net_worth"]) == (
        Decimal("18050.00"),
        Decimal("4000.00"),
        Decimal("14050.00"),
    )
    assert (
        rows["cash", "liquid", "SGD"]["value"],
        rows["public_equity", "liquid", "SGD"]["value"],
        rows["restricted_comp", "restricted", "USD"]["value"],
        rows["real_estate", "illiquid", "SGD"]["value"],
        rows["real_estate", "liability", "SGD"]["value"],
    ) == (Decimal("5200.00"), Decimal("1500.00"), Decimal("1350.00"), Decimal("10000.00"), Decimal("-4000.00"))
    assert (
        rows["public_equity", "liquid", "SGD"]["percentage_of_net_worth"],
        rows["cash", "liquid", "SGD"]["source_line_count"],
        rows["public_equity", "liquid", "SGD"]["source_line_count"],
    ) == (Decimal("10.68"), 2, 2)


async def test_income_statement_includes_applied_classification_breakdown(db: AsyncSession, test_user) -> None:
    rep_date = date(2025, 3, 31)
    [income] = await seed_accounts(db, test_user.id, ("Salary", AccountType.INCOME))
    atomic = AtomicTransaction(
        user_id=test_user.id,
        txn_date=rep_date,
        amount=Decimal("1000.00"),
        direction=TransactionDirection.IN,
        description="Monthly salary",
        currency="SGD",
        dedup_hash=f"cls-{uuid4()}",
        source_documents=[],
    )
    rule = ClassificationRule(
        user_id=test_user.id,
        version_number=1,
        effective_date=rep_date,
        rule_name=f"Salary rule {uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["salary"]},
        default_account_id=income.id,
        created_by=test_user.id,
    )
    db.add_all([atomic, rule])
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
    assert (await generate_income_statement(db, test_user.id, start_date=rep_date, end_date=rep_date, currency="SGD"))[
        "classification_breakdown"
    ] == [{"account_name": "Salary", "account_type": "INCOME", "classified_count": 1, "avg_confidence": 95.0}]
