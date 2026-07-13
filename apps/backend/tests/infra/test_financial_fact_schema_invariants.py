"""Database-level financial fact invariant tests for issue #845."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import ReportSnapshot
from src.extraction.orm.layer2 import AssetType, AtomicPosition, AtomicTransaction, TransactionDirection
from src.extraction.orm.layer3 import (
    ClassificationRule,
    CostBasisMethod,
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
    RuleType,
)
from src.extraction.orm.layer4 import ReportType
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from src.portfolio import DividendIncome, DividendType, InvestmentLot, InvestmentTransaction, InvestmentTransactionType
from src.pricing import MarketDataOverride, PriceSource
from src.pricing.extension.market_data import _load_stored_stock_price
from src.pricing.orm.market_data import FxRate, StockPrice

BACKEND_DIR = Path(__file__).parent.parent.parent
MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "0033_financial_fact_constraints.py"
RISK_PATH = BACKEND_DIR.parent.parent / "docs" / "ssot" / "migration-risk.yaml"


async def _expect_integrity_error(db: AsyncSession, *objects: object) -> None:
    db.add_all(objects)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def _make_account(db: AsyncSession, user_id, *, name: str | None = None) -> Account:
    account = Account(
        user_id=user_id,
        name=name or f"Account {uuid4()}",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(account)
    await db.flush()
    return account


async def _make_rule(db: AsyncSession, user_id, *, version: int = 1) -> ClassificationRule:
    rule = ClassificationRule(
        user_id=user_id,
        version_number=version,
        effective_date=date(2026, 1, 1),
        rule_name=f"schema-invariant-rule-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["schema"]},
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()
    return rule


def _source_documents() -> dict[str, list[dict[str, str]]]:
    return {"documents": [{"doc_id": str(uuid4()), "doc_type": "test"}]}


async def test_AC11_18_1_positive_source_fact_constraints(db: AsyncSession, test_user) -> None:
    """AC-audit.42.1: AC11.18.1: Source facts reject non-positive values where positive is required (transaction
    amount, manual-valuation value); positions are signed and may be negative (short, #1448)."""
    user_id = test_user.id
    await _expect_integrity_error(
        db,
        AtomicTransaction(
            user_id=user_id,
            txn_date=date(2026, 1, 2),
            amount=Decimal("0.00"),
            direction=TransactionDirection.IN,
            description="zero amount should fail",
            currency="USD",
            dedup_hash=uuid4().hex + uuid4().hex,
            source_documents=_source_documents(),
        ),
    )

    # #1448: a short position is signed — negative quantity AND negative market
    # value — and is a valid first-class position (no non-negative constraint).
    short_position = AtomicPosition(
        user_id=user_id,
        snapshot_date=date(2026, 1, 3),
        asset_identifier="AAPL",
        broker="Moomoo",
        quantity=Decimal("-5.000000"),
        market_value=Decimal("-500.00"),
        currency="USD",
        asset_type=AssetType.STOCK,
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=_source_documents(),
    )
    db.add(short_position)
    await db.commit()
    assert short_position.market_value == Decimal("-500.00")

    await _expect_integrity_error(
        db,
        ManualValuationSnapshot(
            user_id=user_id,
            component_type=ManualValuationComponentType.PROPERTY_VALUE,
            liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
            as_of_date=date(2026, 1, 31),
            value=Decimal("0.00"),
            currency="USD",
            source="manual appraisal",
        ),
    )
    await _expect_integrity_error(
        db,
        ManualValuationSnapshot(
            user_id=user_id,
            component_type=ManualValuationComponentType.CPF_BALANCE,
            liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
            as_of_date=date(2026, 1, 31),
            value=Decimal("1000.00"),
            currency="SGD",
            source="manual CPF",
            recurrence_days=0,
        ),
    )


async def test_AC11_18_2_statement_summary_approved_completeness_and_period_order(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-audit.42.2: AC11.18.2: Approved statement summaries require complete envelopes and ordered periods."""
    user_id = test_user.id
    account = await _make_account(db, user_id)
    account_id = account.id
    await db.commit()

    await _expect_integrity_error(
        db,
        StatementSummary(
            user_id=user_id,
            file_hash=uuid4().hex,
            institution="Schema Bank",
            currency="USD",
            period_start=date(2026, 2, 1),
            period_end=date(2026, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            status=BankStatementStatus.PARSED,
        ),
    )

    await _expect_integrity_error(
        db,
        StatementSummary(
            user_id=user_id,
            file_hash=uuid4().hex,
            institution="Schema Bank",
            account_id=account_id,
            currency="USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=None,
            status=BankStatementStatus.APPROVED,
        ),
    )

    await _expect_integrity_error(
        db,
        StatementSummary(
            user_id=user_id,
            file_hash=uuid4().hex,
            institution="Schema Bank",
            currency="USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            status=BankStatementStatus.APPROVED,
        ),
    )

    await _expect_integrity_error(
        db,
        StatementSummary(
            user_id=user_id,
            file_hash=uuid4().hex,
            institution="Schema Bank",
            account_id=account_id,
            currency="   ",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            status=BankStatementStatus.APPROVED,
        ),
    )

    approved = StatementSummary(
        user_id=user_id,
        file_hash=uuid4().hex,
        institution="Schema Bank",
        account_id=account_id,
        currency="USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("110.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(approved)
    await db.commit()


async def test_AC11_18_3_portfolio_fact_constraints_and_managed_position_uniqueness(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-audit.42.3: AC11.18.3: Portfolio facts enforce deterministic uniqueness and disposal/acquisition
    ordering; positions are signed and may carry negative quantity/cost basis (short, #1448)."""
    user_id = test_user.id
    account = await _make_account(db, user_id)
    account_id = account.id
    # #1448: a short managed position is signed — negative quantity AND negative
    # cost_basis — and persists (no non-negative cost_basis constraint).
    position = ManagedPosition(
        user_id=user_id,
        account_id=account_id,
        asset_identifier="AAPL",
        quantity=Decimal("-5.000000"),
        cost_basis=Decimal("-500.00"),
        cost_basis_method=CostBasisMethod.FIFO,
        acquisition_date=date(2026, 1, 2),
        status=PositionStatus.ACTIVE,
        currency="USD",
    )
    db.add(position)
    await db.commit()
    position_id = position.id
    assert position.cost_basis == Decimal("-500.00")

    await _expect_integrity_error(
        db,
        ManagedPosition(
            user_id=user_id,
            account_id=account_id,
            asset_identifier="AAPL",
            quantity=Decimal("1.000000"),
            cost_basis=Decimal("100.00"),
            acquisition_date=date(2026, 1, 3),
            status=PositionStatus.ACTIVE,
            currency="USD",
        ),
    )
    await _expect_integrity_error(
        db,
        ManagedPosition(
            user_id=user_id,
            account_id=account_id,
            asset_identifier="NVDA",
            quantity=Decimal("1.000000"),
            cost_basis=Decimal("1.00"),
            acquisition_date=date(2026, 1, 5),
            disposal_date=date(2026, 1, 4),
            status=PositionStatus.DISPOSED,
            currency="USD",
        ),
    )

    transaction = InvestmentTransaction(
        user_id=user_id,
        position_id=position_id,
        transaction_date=date(2026, 1, 4),
        transaction_type=InvestmentTransactionType.BUY,
        asset_identifier="AAPL",
        quantity=Decimal("10.000000"),
        unit_price=Decimal("10.000000"),
        gross_amount=Decimal("100.00"),
        fees=Decimal("0.00"),
        currency="USD",
        cost_basis=Decimal("100.00"),
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(transaction)
    await db.commit()
    transaction_id = transaction.id

    await _expect_integrity_error(
        db,
        InvestmentTransaction(
            user_id=user_id,
            position_id=position_id,
            transaction_date=date(2026, 1, 5),
            transaction_type=InvestmentTransactionType.BUY,
            asset_identifier="AAPL",
            quantity=Decimal("-1.000000"),
            unit_price=Decimal("10.000000"),
            gross_amount=Decimal("10.00"),
            fees=Decimal("0.00"),
            currency="USD",
            cost_basis=Decimal("10.00"),
            cost_basis_method=CostBasisMethod.FIFO,
        ),
    )
    await _expect_integrity_error(
        db,
        InvestmentTransaction(
            user_id=user_id,
            position_id=position_id,
            transaction_date=date(2026, 1, 5),
            transaction_type=InvestmentTransactionType.DIVIDEND,
            asset_identifier="AAPL",
            gross_amount=Decimal("0.00"),
            fees=Decimal("0.00"),
            currency="USD",
        ),
    )
    await _expect_integrity_error(
        db,
        InvestmentLot(
            user_id=user_id,
            position_id=position_id,
            opening_transaction_id=transaction_id,
            asset_identifier="AAPL",
            acquisition_date=date(2026, 1, 4),
            original_quantity=Decimal("10.000000"),
            remaining_quantity=Decimal("11.000000"),
            unit_cost=Decimal("10.000000"),
            currency="USD",
        ),
    )
    await _expect_integrity_error(
        db,
        DividendIncome(
            user_id=user_id,
            position_id=position_id,
            payment_date=date(2026, 2, 1),
            amount=Decimal("0.00"),
            currency="USD",
            dividend_type=DividendType.ORDINARY,
        ),
    )


async def test_AC11_18_4_report_snapshot_latest_scope_and_date_constraints(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-audit.42.4: AC11.18.4: Latest report snapshots are unique per logical report scope."""
    user_id = test_user.id
    rule = await _make_rule(db, user_id, version=1)
    second_rule = await _make_rule(db, user_id, version=2)
    rule_id = rule.id
    second_rule_id = second_rule.id
    await db.commit()

    await _expect_integrity_error(
        db,
        ReportSnapshot(
            user_id=user_id,
            report_type=ReportType.INCOME_STATEMENT,
            start_date=date(2026, 2, 1),
            as_of_date=date(2026, 1, 31),
            rule_version_id=rule_id,
            report_data={"total_income": "1.00"},
            is_latest=True,
        ),
    )

    history_one = ReportSnapshot(
        user_id=user_id,
        report_type=ReportType.BALANCE_SHEET,
        as_of_date=date(2026, 1, 31),
        rule_version_id=rule_id,
        report_data={"version": 1},
        is_latest=False,
    )
    history_two = ReportSnapshot(
        user_id=user_id,
        report_type=ReportType.BALANCE_SHEET,
        as_of_date=date(2026, 1, 31),
        rule_version_id=rule_id,
        report_data={"version": 2},
        is_latest=False,
    )
    db.add_all([history_one, history_two])
    await db.commit()

    latest = ReportSnapshot(
        user_id=user_id,
        report_type=ReportType.BALANCE_SHEET,
        as_of_date=date(2026, 1, 31),
        rule_version_id=rule_id,
        report_data={"version": 3},
        is_latest=True,
    )
    db.add(latest)
    await db.commit()

    await _expect_integrity_error(
        db,
        ReportSnapshot(
            user_id=user_id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=date(2026, 1, 31),
            rule_version_id=second_rule_id,
            report_data={"version": 4},
            is_latest=True,
        ),
    )


async def test_AC11_18_5_market_data_constraints_and_stock_price_uniqueness(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-audit.42.5: AC11.18.5: Market facts are positive and stock-price uniqueness includes provider dimensions."""
    user_id = test_user.id
    await _expect_integrity_error(
        db,
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("0.000000"),
            rate_date=date(2026, 1, 5),
            source="test",
        ),
    )
    await _expect_integrity_error(
        db,
        StockPrice(
            symbol="AAPL",
            price=Decimal("0.000000"),
            currency="USD",
            price_date=date(2026, 1, 5),
            source="test",
        ),
    )

    first_price = StockPrice(
        symbol="AAPL",
        price=Decimal("100.000000"),
        currency="USD",
        price_date=date(2026, 1, 5),
        source="alpha",
        created_at=datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
    )
    second_price = StockPrice(
        symbol="AAPL",
        price=Decimal("101.000000"),
        currency="USD",
        price_date=date(2026, 1, 5),
        source="beta",
        created_at=datetime(2026, 1, 5, 13, 0, tzinfo=UTC),
    )
    db.add_all([first_price, second_price])
    await db.commit()

    stored = await _load_stored_stock_price(db, "aapl", date(2026, 1, 5))
    assert stored is not None
    assert stored.price == Decimal("101.000000")
    assert stored.source == "beta"

    await _expect_integrity_error(
        db,
        StockPrice(
            symbol="AAPL",
            price=Decimal("102.000000"),
            currency="USD",
            price_date=date(2026, 1, 5),
            source="beta",
        ),
    )
    await _expect_integrity_error(
        db,
        MarketDataOverride(
            user_id=user_id,
            asset_identifier="AAPL",
            price_date=date(2026, 1, 5),
            price=Decimal("0.00"),
            currency="USD",
            source=PriceSource.MANUAL,
        ),
    )


@pytest.mark.no_db
def test_AC11_18_6_migration_preflights_and_risk_contract_are_declared() -> None:
    """AC-audit.42.6: AC11.18.6: The migration declares preflight checks and risk classification."""
    migration_source = MIGRATION_PATH.read_text()
    risk_source = RISK_PATH.read_text()

    for expected in (
        "preflight failed: atomic_transactions contains non-positive amounts",
        "preflight failed: approved statement_summaries are missing required envelope fields",
        "preflight failed: duplicate latest report_snapshots exist",
        "preflight failed: duplicate managed_positions exist for deterministic scope",
        "preflight failed: stock_prices contain duplicate provider-scoped facts",
    ):
        assert expected in migration_source

    assert "NULLIF(BTRIM(currency), '') IS NULL" in migration_source
    assert "0033_financial_fact_constraints" in risk_source
    assert 'issue: "#845"' in risk_source
    assert "preflight" in risk_source
