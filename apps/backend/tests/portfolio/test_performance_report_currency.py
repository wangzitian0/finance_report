"""Presentation currency consistency tests for investment performance report schedule (#2923)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account, AccountType
from src.portfolio import build_investment_performance_report_schedule
from src.portfolio.orm.portfolio import (
    CostBasisMethod,
    InvestmentTransaction,
    InvestmentTransactionType,
    ManagedPosition,
    PositionStatus,
)
from src.pricing.orm.market_data import FxRate


async def _seed_usd_position_with_sgd_fx(db: AsyncSession, user_id: object) -> tuple[date, date, date]:
    acq_date = date(2026, 1, 10)
    period_start = date(2026, 1, 1)
    as_of_date = date(2026, 3, 31)

    account = Account(user_id=user_id, name="USD Broker", type=AccountType.ASSET, currency="USD")
    db.add(account)
    await db.flush()

    position = ManagedPosition(
        user_id=user_id,
        account_id=account.id,
        asset_identifier="VOO",
        quantity=Decimal("1"),
        cost_basis=Decimal("100.00"),
        currency="USD",
        acquisition_date=acq_date,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    atomic = AtomicPosition(
        user_id=user_id,
        snapshot_date=as_of_date,
        asset_identifier="VOO",
        broker="USD Broker",
        quantity=Decimal("1"),
        market_value=Decimal("110.00"),
        currency="USD",
        sector="Equity",
        geography="US",
        asset_type="etf",
        dedup_hash="voo_2923_snapshot",
        source_documents={},
    )
    db.add(position)
    await db.flush()
    db.add_all(
        [
            atomic,
            # The BUY row is the source of the cost at a past date (#2920).
            InvestmentTransaction(
                user_id=user_id,
                position_id=position.id,
                transaction_date=acq_date,
                transaction_type=InvestmentTransactionType.BUY,
                asset_identifier="VOO",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                gross_amount=Decimal("100.00"),
                fees=Decimal("0.00"),
                currency="USD",
                cost_basis=Decimal("100.00"),
                realized_pnl=Decimal("0.00"),
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=acq_date, source="test"),
            FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=as_of_date, source="test"),
        ]
    )
    await db.flush()
    return period_start, as_of_date, as_of_date


async def test_performance_schedule_converts_holdings_and_totals_to_sgd_when_base_is_usd(
    db: AsyncSession, test_user
) -> None:
    """Convert holding rows and schedule totals to presentation currency SGD when user base is USD."""
    period_start, period_end, as_of_date = await _seed_usd_position_with_sgd_fx(db, test_user.id)

    schedule = await build_investment_performance_report_schedule(
        db,
        test_user.id,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        currency="SGD",
        base_currency="USD",
    )

    assert len(schedule.holdings) == 1
    row = schedule.holdings[0]
    assert row.cost_basis == Decimal("135.00")
    assert row.market_value == Decimal("148.50")
    assert row.unrealized_pnl == Decimal("13.50")
    assert row.currency == "SGD"
    assert schedule.unrealized_pnl == Decimal("13.50")
    assert schedule.currency == "SGD"


async def test_performance_schedule_keeps_usd_when_presentation_and_base_are_usd(
    db: AsyncSession, test_user
) -> None:
    """Keep USD figures unchanged when both presentation currency and base currency are USD."""
    period_start, period_end, as_of_date = await _seed_usd_position_with_sgd_fx(db, test_user.id)

    schedule = await build_investment_performance_report_schedule(
        db,
        test_user.id,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        currency="USD",
        base_currency="USD",
    )

    assert len(schedule.holdings) == 1
    row = schedule.holdings[0]
    assert row.cost_basis == Decimal("100.00")
    assert row.market_value == Decimal("110.00")
    assert row.unrealized_pnl == Decimal("10.00")
    assert row.currency == "USD"
    assert schedule.unrealized_pnl == Decimal("10.00")
    assert schedule.currency == "USD"
