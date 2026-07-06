"""AC17.5/AC17.6: Investment transaction accounting tests."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntryStatus
from src.models.layer3 import CostBasisMethod, PositionStatus
from src.models.portfolio import DividendIncome, InvestmentLot, InvestmentTransaction
from src.portfolio import InvestmentAccountingService, InvestmentAccountingValidationError


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
        "withholding_tax": Account(
            user_id=test_user.id,
            name="Dividend Withholding Tax",
            type=AccountType.EXPENSE,
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


class _ScalarStub:
    def __init__(self, value):
        self.value = value

    async def scalar(self, _query):
        return self.value


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


async def test_transaction_currency_must_match_position_currency(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC-audit.35.2: a transaction in a currency other than the position's raises a clean
    domain error (not a raw CurrencyMismatchError) once Money arithmetic is used."""
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
    with pytest.raises(InvestmentAccountingValidationError, match="currency"):
        await svc.post_buy(
            db,
            user_id=test_user.id,
            transaction_date=date(2026, 1, 6),
            asset_identifier="VWRA",
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            currency="USD",
            cash_account_id=chart["cash"].id,
            investment_account_id=chart["investment"].id,
        )


async def test_sell_transaction_uses_fifo_and_records_realized_gain(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.1.2 AC17.5.2 AC17.6.1: Sell transactions consume FIFO lots and record realized P&L."""
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


async def test_sell_transaction_uses_average_cost_for_realized_pnl(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.1.4 AC17.5.2: Average cost basis is explicit and persisted on sell transactions."""
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


async def test_sell_transaction_uses_lifo_loss_and_disposes_position(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.1.3 AC17.5.2 AC17.6.1: LIFO sells can realize losses and close positions."""
    await svc.post_buy(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 1, 5),
        asset_identifier="SWRD",
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
        asset_identifier="SWRD",
        quantity=Decimal("5"),
        unit_price=Decimal("120.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
    )

    loss = await svc.post_sell(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 3, 5),
        asset_identifier="SWRD",
        quantity=Decimal("5"),
        unit_price=Decimal("110.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
        realized_pnl_account_id=chart["realized_pnl"].id,
        cost_basis_method=CostBasisMethod.LIFO,
    )

    assert _line_amount(loss.journal_entry, chart["realized_pnl"].id, Direction.DEBIT) == Decimal("50.00")
    assert loss.transaction.cost_basis == Decimal("600.00")
    assert loss.transaction.realized_pnl == Decimal("-50.00")

    closed = await svc.post_sell(
        db,
        user_id=test_user.id,
        transaction_date=date(2026, 4, 5),
        asset_identifier="SWRD",
        quantity=Decimal("10"),
        unit_price=Decimal("100.00"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
        realized_pnl_account_id=chart["realized_pnl"].id,
        cost_basis_method=CostBasisMethod.LIFO,
    )

    assert closed.position.quantity == Decimal("0")
    assert closed.position.status == PositionStatus.DISPOSED
    assert closed.position.disposal_date == date(2026, 4, 5)


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


async def test_dividend_transaction_posts_withholding_tax(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.5.3/AC17.6.2: Withholding tax splits dividend cash and tax expense."""
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

    result = await svc.post_dividend(
        db,
        user_id=test_user.id,
        payment_date=date(2026, 4, 5),
        asset_identifier="VWRA",
        gross_amount=Decimal("25.00"),
        withholding_tax=Decimal("7.50"),
        currency="SGD",
        cash_account_id=chart["cash"].id,
        investment_account_id=chart["investment"].id,
        dividend_income_account_id=chart["dividend_income"].id,
        withholding_tax_account_id=chart["withholding_tax"].id,
    )

    assert _line_amount(result.journal_entry, chart["cash"].id, Direction.DEBIT) == Decimal("17.50")
    assert _line_amount(result.journal_entry, chart["withholding_tax"].id, Direction.DEBIT) == Decimal("7.50")
    assert _line_amount(result.journal_entry, chart["dividend_income"].id, Direction.CREDIT) == Decimal("25.00")


async def test_investment_accounting_rejects_invalid_transactions(
    db: AsyncSession,
    test_user,
    chart,
    svc: InvestmentAccountingService,
):
    """AC17.5.1/AC17.5.2/AC17.5.3: Invalid transaction inputs are rejected."""
    with pytest.raises(InvestmentAccountingValidationError, match="buy amount must be positive"):
        await svc.post_buy(
            db,
            user_id=test_user.id,
            transaction_date=date(2026, 1, 5),
            asset_identifier="VWRA",
            quantity=Decimal("10"),
            unit_price=Decimal("0.00"),
            currency="SGD",
            cash_account_id=chart["cash"].id,
            investment_account_id=chart["investment"].id,
        )

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

    with pytest.raises(InvestmentAccountingValidationError, match="sell proceeds must be positive"):
        await svc.post_sell(
            db,
            user_id=test_user.id,
            transaction_date=date(2026, 2, 5),
            asset_identifier="VWRA",
            quantity=Decimal("1"),
            unit_price=Decimal("0.00"),
            currency="SGD",
            cash_account_id=chart["cash"].id,
            investment_account_id=chart["investment"].id,
            realized_pnl_account_id=chart["realized_pnl"].id,
        )

    with pytest.raises(InvestmentAccountingValidationError, match="only 10.000000 available"):
        await svc.post_sell(
            db,
            user_id=test_user.id,
            transaction_date=date(2026, 2, 5),
            asset_identifier="VWRA",
            quantity=Decimal("11"),
            unit_price=Decimal("100.00"),
            currency="SGD",
            cash_account_id=chart["cash"].id,
            investment_account_id=chart["investment"].id,
            realized_pnl_account_id=chart["realized_pnl"].id,
        )

    with pytest.raises(InvestmentAccountingValidationError, match="withholding_tax cannot exceed gross_amount"):
        await svc.post_dividend(
            db,
            user_id=test_user.id,
            payment_date=date(2026, 4, 5),
            asset_identifier="VWRA",
            gross_amount=Decimal("25.00"),
            withholding_tax=Decimal("25.01"),
            currency="SGD",
            cash_account_id=chart["cash"].id,
            investment_account_id=chart["investment"].id,
            dividend_income_account_id=chart["dividend_income"].id,
        )

    with pytest.raises(InvestmentAccountingValidationError, match="withholding_tax_account_id is required"):
        await svc.post_dividend(
            db,
            user_id=test_user.id,
            payment_date=date(2026, 4, 5),
            asset_identifier=buy.position.asset_identifier,
            gross_amount=Decimal("25.00"),
            withholding_tax=Decimal("7.50"),
            currency="SGD",
            cash_account_id=chart["cash"].id,
            investment_account_id=chart["investment"].id,
            dividend_income_account_id=chart["dividend_income"].id,
        )

    with pytest.raises(InvestmentAccountingValidationError, match="position UNKNOWN not found"):
        await svc.post_dividend(
            db,
            user_id=test_user.id,
            payment_date=date(2026, 4, 5),
            asset_identifier="UNKNOWN",
            gross_amount=Decimal("25.00"),
            currency="SGD",
            cash_account_id=chart["cash"].id,
            investment_account_id=chart["investment"].id,
            dividend_income_account_id=chart["dividend_income"].id,
        )


async def test_investment_accounting_rejects_invalid_account_and_position_helpers(
    svc: InvestmentAccountingService,
):
    """AC17.5.1/AC17.5.2: Ledger helpers reject invalid accounts and missing positions."""
    user_id = uuid4()
    account_id = uuid4()

    with pytest.raises(InvestmentAccountingValidationError, match=f"account {account_id} not found"):
        await svc._get_account(_ScalarStub(None), user_id, account_id, AccountType.ASSET)

    liability_account = SimpleNamespace(name="Loan", type=AccountType.LIABILITY, is_active=True)
    with pytest.raises(InvestmentAccountingValidationError, match="account Loan must be ASSET"):
        await svc._get_account(_ScalarStub(liability_account), user_id, account_id, AccountType.ASSET)

    inactive_account = SimpleNamespace(name="Closed Cash", type=AccountType.ASSET, is_active=False)
    with pytest.raises(InvestmentAccountingValidationError, match="account Closed Cash is inactive"):
        await svc._get_account(_ScalarStub(inactive_account), user_id, account_id, AccountType.ASSET)

    with pytest.raises(InvestmentAccountingValidationError, match="position MISSING not found"):
        await svc._get_position(
            _ScalarStub(None),
            user_id=user_id,
            account_id=account_id,
            asset_identifier="MISSING",
        )
