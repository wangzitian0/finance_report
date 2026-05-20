"""AC17.5/AC17.6: Investment transaction accounting tests."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntryStatus
from src.models.layer3 import CostBasisMethod
from src.models.portfolio import DividendIncome, InvestmentLot, InvestmentTransaction
from src.services.investment_accounting import InvestmentAccountingService


@pytest.fixture
async def chart(db: AsyncSession, test_user):
    accounts = {
        "cash": Account(
            user_id=test_user.id,
            name="Brokerage Cash",
            type=AccountType.ASSET,
            currency="SGD",
        ),
        "investment": Account(
            user_id=test_user.id,
            name="Investment Securities",
            type=AccountType.ASSET,
            currency="SGD",
        ),
        "realized_pnl": Account(
            user_id=test_user.id,
            name="Realized Investment P&L",
            type=AccountType.INCOME,
            currency="SGD",
        ),
        "dividend_income": Account(
            user_id=test_user.id,
            name="Dividend Income",
            type=AccountType.INCOME,
            currency="SGD",
        ),
    }
    db.add_all(accounts.values())
    await db.flush()
    return accounts


@pytest.fixture
def svc() -> InvestmentAccountingService:
    return InvestmentAccountingService()


def _line_amount(entry, account_id, direction):
    return next(line.amount for line in entry.lines if line.account_id == account_id and line.direction == direction)


@pytest.mark.asyncio
async def test_buy_transaction_creates_balanced_journal_entry_and_lot(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.5.1: Buy transactions increase investments and reduce brokerage cash."""
    result = await svc.post_buy(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 1, 5),
        asset_identifier="VWRA",
        quantity=Decimal("10"),
        unit_price=Decimal("100.00"),
        fees=Decimal("5.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
    )

    assert result.journal_entry.status == JournalEntryStatus.POSTED
    assert _line_amount(result.journal_entry, chart["investment"].id, Direction.DEBIT) == Decimal("1005.00")
    assert _line_amount(result.journal_entry, chart["cash"].id, Direction.CREDIT) == Decimal("1005.00")
    assert result.position.quantity == Decimal("10")
    assert result.position.cost_basis == Decimal("1005.00")

    lots = (
        (await db.execute(select(InvestmentLot).where(InvestmentLot.position_id == result.position.id))).scalars().all()
    )
    assert len(lots) == 1
    assert lots[0].remaining_quantity == Decimal("10")
    assert lots[0].unit_cost == Decimal("100.500000")


@pytest.mark.asyncio
async def test_sell_transaction_uses_fifo_and_records_realized_gain(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.5.2/AC17.6.1: Sell transactions consume FIFO lots and record realized P&L."""
    await svc.post_buy(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 1, 5),
        asset_identifier="VWRA",
        quantity=Decimal("10"),
        unit_price=Decimal("100.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
    )
    await svc.post_buy(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 2, 5),
        asset_identifier="VWRA",
        quantity=Decimal("5"),
        unit_price=Decimal("120.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
    )

    result = await svc.post_sell(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 3, 5),
        asset_identifier="VWRA",
        quantity=Decimal("12"),
        unit_price=Decimal("130.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
        realized_pnl_account_id=chart["realized_pnl"].id,
        cost_basis_method=CostBasisMethod.FIFO,
    )

    assert _line_amount(result.journal_entry, chart["cash"].id, Direction.DEBIT) == Decimal("1560.00")
    assert _line_amount(result.journal_entry, chart["investment"].id, Direction.CREDIT) == Decimal("1240.00")
    assert _line_amount(result.journal_entry, chart["realized_pnl"].id, Direction.CREDIT) == Decimal("320.00")
    assert result.transaction.cost_basis == Decimal("1240.00")
    assert result.transaction.realized_pnl == Decimal("320.00")
    assert result.position.quantity == Decimal("3")
    assert result.position.cost_basis == Decimal("360.00")
    assert result.position.realized_pnl == Decimal("320.00")

    remaining = (
        (
            await db.execute(
                select(InvestmentLot)
                .where(InvestmentLot.position_id == result.position.id)
                .order_by(InvestmentLot.acquisition_date)
            )
        )
        .scalars()
        .all()
    )
    assert [lot.remaining_quantity for lot in remaining] == [Decimal("0"), Decimal("3")]


@pytest.mark.asyncio
async def test_sell_transaction_uses_average_cost_for_realized_pnl(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.5.2: Average cost basis is explicit and persisted on sell transactions."""
    await svc.post_buy(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 1, 5),
        asset_identifier="AAPL",
        quantity=Decimal("10"),
        unit_price=Decimal("100.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
    )
    await svc.post_buy(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 2, 5),
        asset_identifier="AAPL",
        quantity=Decimal("10"),
        unit_price=Decimal("140.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
    )

    result = await svc.post_sell(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 3, 5),
        asset_identifier="AAPL",
        quantity=Decimal("5"),
        unit_price=Decimal("150.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
        realized_pnl_account_id=chart["realized_pnl"].id,
        cost_basis_method=CostBasisMethod.AVGCOST,
    )

    assert result.transaction.cost_basis_method == CostBasisMethod.AVGCOST
    assert result.transaction.cost_basis == Decimal("600.00")
    assert result.transaction.realized_pnl == Decimal("150.00")
    assert result.position.cost_basis == Decimal("1800.00")


@pytest.mark.asyncio
async def test_dividend_transaction_posts_income_and_dividend_record(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.5.3/AC17.6.2: Dividends create cash, income, and DividendIncome records."""
    buy = await svc.post_buy(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 1, 5),
        asset_identifier="VWRA",
        quantity=Decimal("10"),
        unit_price=Decimal("100.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
    )

    result = await svc.post_dividend(
        db,
        user_id=test_user.id,
        payment_date=date(2026, 4, 5),
        asset_identifier="VWRA",
        gross_amount=Decimal("25.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
        dividend_income_account_id=chart["dividend_income"].id,
    )

    assert result.position.id == buy.position.id
    assert _line_amount(result.journal_entry, chart["cash"].id, Direction.DEBIT) == Decimal("25.00")
    assert _line_amount(result.journal_entry, chart["dividend_income"].id, Direction.CREDIT) == Decimal("25.00")

    dividend = (
        await db.execute(select(DividendIncome).where(DividendIncome.position_id == buy.position.id))
    ).scalar_one()
    assert dividend.amount == Decimal("25.00")

    transactions = (
        (
            await db.execute(
                select(InvestmentTransaction)
                .where(InvestmentTransaction.position_id == buy.position.id)
                .order_by(InvestmentTransaction.transaction_date)
            )
        )
        .scalars()
        .all()
    )
    assert [txn.transaction_type.value for txn in transactions] == ["buy", "dividend"]
