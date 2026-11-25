import inspect
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.composition import _balance_sheet_disposition_for, _get_or_create_default_counter_account
from src.extraction.base.disposition import EconomicIntent
from src.extraction.base.source_vocabulary import TransactionDirection
from src.extraction.extension.transaction_classification import ClassificationSuggestion, TransactionCategory
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, AccountType, Direction, JournalEntryStatus
from src.portfolio import (
    DividendEvent,
    DividendIncome,
    InvestmentAccountingService,
    InvestmentAccountingValidationError,
    InvestmentLot,
    InvestmentTransaction,
    TradeAccounts,
    TradeOrder,
)
from src.portfolio.orm.portfolio import CostBasisMethod, PositionStatus


@pytest.fixture
async def chart(db: AsyncSession, test_user):
    accounts = {
        "cash": Account(user_id=test_user.id, name="Brokerage Cash", type=AccountType.ASSET, currency="SGD"),
        "investment": Account(
            user_id=test_user.id, name="Investment Securities", type=AccountType.ASSET, currency="SGD"
        ),
        "realized_pnl": Account(
            user_id=test_user.id, name="Realized Investment P&L", type=AccountType.INCOME, currency="SGD"
        ),
        "dividend_income": Account(
            user_id=test_user.id, name="Dividend Income", type=AccountType.INCOME, currency="SGD"
        ),
        "withholding_tax": Account(
            user_id=test_user.id, name="Dividend Withholding Tax", type=AccountType.EXPENSE, currency="SGD"
        ),
    }
    db.add_all(accounts.values())
    await db.flush()
    return accounts


@pytest.fixture
def svc() -> InvestmentAccountingService:
    return InvestmentAccountingService()


def _line_amount(entry, account_id, direction: Direction) -> Decimal:
    return next(line.amount for line in entry.lines if line.account_id == account_id and line.direction == direction)


def _accounts(
    chart: dict[str, Account], *, with_pnl: bool = False, with_div: bool = False, with_wht: bool = False
) -> TradeAccounts:
    return TradeAccounts(
        cash=chart["cash"].id,
        investment=chart["investment"].id,
        realized_pnl=chart["realized_pnl"].id if with_pnl else None,
        dividend_income=chart["dividend_income"].id if with_div else None,
        withholding_tax=chart["withholding_tax"].id if with_wht else None,
    )


def _order(
    tx_date: date,
    asset: str,
    qty: Decimal,
    price: Decimal,
    *,
    currency: str = "SGD",
    fees: Decimal = Decimal("0.00"),
    method: CostBasisMethod = CostBasisMethod.FIFO,
) -> TradeOrder:
    return TradeOrder.create(
        transaction_date=tx_date,
        asset_identifier=asset,
        quantity=qty,
        unit_price=price,
        currency=currency,
        fees=fees,
        cost_basis_method=method.value,
    )


async def test_AC_portfolio_posting_inputs_1_value_objects_bound_the_write_signature(chart) -> None:
    order = _order(date(2026, 1, 5), "VWRA", Decimal("10"), Decimal("100.00"))
    accounts = _accounts(chart, with_pnl=True)
    dividend = DividendEvent.create(
        payment_date=date(2026, 4, 5), asset_identifier="VWRA", gross_amount=Decimal("25.00"), currency="SGD"
    )
    assert (
        order.quantity.value,
        order.unit_price.rate,
        accounts.investment,
        dividend.gross_amount.amount,
        list(inspect.signature(InvestmentAccountingService.post_buy).parameters),
        inspect.getsource(InvestmentAccountingService).count("fees=order.fees.quantize().amount"),
    ) == (
        Decimal("10"),
        Decimal("100.00"),
        chart["investment"].id,
        Decimal("25.00"),
        ["self", "db", "user_id", "order", "accounts"],
        2,
    )


async def test_buy_and_currency_mismatch_guard(db: AsyncSession, test_user, chart, svc: InvestmentAccountingService):
    res = await svc.post_buy(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 1, 5), "VWRA", Decimal("10"), Decimal("100.00"), fees=Decimal("5.00")),
        accounts=_accounts(chart),
    )
    lots = (await db.execute(select(InvestmentLot).where(InvestmentLot.position_id == res.position.id))).scalars().all()
    assert (
        res.journal_entry.status,
        _line_amount(res.journal_entry, chart["investment"].id, Direction.DEBIT),
        _line_amount(res.journal_entry, chart["cash"].id, Direction.CREDIT),
        res.position.quantity,
        res.position.cost_basis,
        len(lots),
        lots[0].remaining_quantity,
        lots[0].unit_cost,
    ) == (
        JournalEntryStatus.POSTED,
        Decimal("1005.00"),
        Decimal("1005.00"),
        Decimal("10"),
        Decimal("1005.00"),
        1,
        Decimal("10"),
        Decimal("100.500000"),
    )
    with pytest.raises(InvestmentAccountingValidationError, match="currency"):
        await svc.post_buy(
            db,
            user_id=test_user.id,
            order=_order(date(2026, 1, 6), "VWRA", Decimal("1"), Decimal("100.00"), currency="USD"),
            accounts=_accounts(chart),
        )


async def test_sell_transaction_fifo_avgcost_and_lifo(
    db: AsyncSession, test_user, chart, svc: InvestmentAccountingService
):
    accts = _accounts(chart, with_pnl=True)
    for asset, q1, p1, q2, p2 in (
        ("VWRA", "10", "100.00", "5", "120.00"),
        ("AAPL", "10", "100.00", "10", "140.00"),
        ("SWRD", "10", "100.00", "5", "120.00"),
    ):
        await svc.post_buy(
            db, user_id=test_user.id, order=_order(date(2026, 1, 5), asset, Decimal(q1), Decimal(p1)), accounts=accts
        )
        await svc.post_buy(
            db, user_id=test_user.id, order=_order(date(2026, 2, 5), asset, Decimal(q2), Decimal(p2)), accounts=accts
        )
    fifo = await svc.post_sell(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 3, 5), "VWRA", Decimal("12"), Decimal("130.00"), method=CostBasisMethod.FIFO),
        accounts=accts,
    )
    fifo_lots = (
        (
            await db.execute(
                select(InvestmentLot)
                .where(InvestmentLot.position_id == fifo.position.id)
                .order_by(InvestmentLot.acquisition_date)
            )
        )
        .scalars()
        .all()
    )
    avg = await svc.post_sell(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 3, 5), "AAPL", Decimal("5"), Decimal("150.00"), method=CostBasisMethod.AVGCOST),
        accounts=accts,
    )
    lifo_loss = await svc.post_sell(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 3, 5), "SWRD", Decimal("5"), Decimal("110.00"), method=CostBasisMethod.LIFO),
        accounts=accts,
    )
    closed = await svc.post_sell(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 4, 5), "SWRD", Decimal("10"), Decimal("100.00"), method=CostBasisMethod.LIFO),
        accounts=accts,
    )
    assert (
        (
            _line_amount(fifo.journal_entry, chart["cash"].id, Direction.DEBIT),
            _line_amount(fifo.journal_entry, chart["investment"].id, Direction.CREDIT),
            _line_amount(fifo.journal_entry, chart["realized_pnl"].id, Direction.CREDIT),
            fifo.transaction.cost_basis,
            fifo.transaction.realized_pnl,
            fifo.position.quantity,
            fifo.position.cost_basis,
            fifo.position.realized_pnl,
            [lot.remaining_quantity for lot in fifo_lots],
        ),
        (
            avg.transaction.cost_basis_method,
            avg.transaction.cost_basis,
            avg.transaction.realized_pnl,
            avg.position.cost_basis,
        ),
        (
            _line_amount(lifo_loss.journal_entry, chart["realized_pnl"].id, Direction.DEBIT),
            lifo_loss.transaction.cost_basis,
            lifo_loss.transaction.realized_pnl,
            closed.position.quantity,
            closed.position.status,
            closed.position.disposal_date,
        ),
    ) == (
        (
            Decimal("1560.00"),
            Decimal("1240.00"),
            Decimal("320.00"),
            Decimal("1240.00"),
            Decimal("320.00"),
            Decimal("3"),
            Decimal("360.00"),
            Decimal("320.00"),
            [Decimal("0"), Decimal("3")],
        ),
        (CostBasisMethod.AVGCOST, Decimal("600.00"), Decimal("150.00"), Decimal("1800.00")),
        (
            Decimal("50.00"),
            Decimal("600.00"),
            Decimal("-50.00"),
            Decimal("0"),
            PositionStatus.DISPOSED,
            date(2026, 4, 5),
        ),
    )


async def test_dividend_transaction_with_and_without_withholding_tax(
    db: AsyncSession, test_user, chart, svc: InvestmentAccountingService
):
    buy = await svc.post_buy(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 1, 5), "VWRA", Decimal("10"), Decimal("100.00")),
        accounts=_accounts(chart),
    )
    plain = await svc.post_dividend(
        db,
        user_id=test_user.id,
        event=DividendEvent.create(
            payment_date=date(2026, 4, 5), asset_identifier="VWRA", gross_amount=Decimal("25.00"), currency="SGD"
        ),
        accounts=_accounts(chart, with_div=True),
    )
    taxed = await svc.post_dividend(
        db,
        user_id=test_user.id,
        event=DividendEvent.create(
            payment_date=date(2026, 4, 6),
            asset_identifier="VWRA",
            gross_amount=Decimal("25.00"),
            withholding_tax=Decimal("7.50"),
            currency="SGD",
        ),
        accounts=_accounts(chart, with_div=True, with_wht=True),
    )
    div_row = (
        await db.execute(
            select(DividendIncome).where(
                DividendIncome.position_id == buy.position.id, DividendIncome.payment_date == date(2026, 4, 5)
            )
        )
    ).scalar_one()
    txns = (
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
    assert (
        plain.position.id,
        _line_amount(plain.journal_entry, chart["cash"].id, Direction.DEBIT),
        _line_amount(plain.journal_entry, chart["dividend_income"].id, Direction.CREDIT),
        div_row.amount,
        [t.transaction_type.value for t in txns],
        _line_amount(taxed.journal_entry, chart["cash"].id, Direction.DEBIT),
        _line_amount(taxed.journal_entry, chart["withholding_tax"].id, Direction.DEBIT),
        _line_amount(taxed.journal_entry, chart["dividend_income"].id, Direction.CREDIT),
    ) == (
        buy.position.id,
        Decimal("25.00"),
        Decimal("25.00"),
        Decimal("25.00"),
        ["buy", "dividend", "dividend"],
        Decimal("17.50"),
        Decimal("7.50"),
        Decimal("25.00"),
    )


async def test_investment_accounting_rejects_invalid_transactions_and_helpers(
    db: AsyncSession, test_user, chart, svc: InvestmentAccountingService
):
    accts = _accounts(chart, with_pnl=True, with_div=True)
    with pytest.raises(InvestmentAccountingValidationError, match="buy amount must be positive"):
        await svc.post_buy(
            db,
            user_id=test_user.id,
            order=_order(date(2026, 1, 5), "VWRA", Decimal("10"), Decimal("0.00")),
            accounts=accts,
        )
    buy = await svc.post_buy(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 1, 5), "VWRA", Decimal("10"), Decimal("100.00")),
        accounts=accts,
    )
    for qty, price, match in (
        (Decimal("1"), Decimal("0.00"), "sell proceeds must be positive"),
        (Decimal("11"), Decimal("100.00"), "only 10.000000 available"),
    ):
        with pytest.raises(InvestmentAccountingValidationError, match=match):
            await svc.post_sell(
                db, user_id=test_user.id, order=_order(date(2026, 2, 5), "VWRA", qty, price), accounts=accts
            )
    for asset, wht, match in (
        ("VWRA", Decimal("25.01"), "withholding_tax cannot exceed gross_amount"),
        (buy.position.asset_identifier, Decimal("7.50"), "withholding_tax_account_id is required"),
        ("UNKNOWN", Decimal("0.00"), "position UNKNOWN not found"),
    ):
        with pytest.raises(InvestmentAccountingValidationError, match=match):
            await svc.post_dividend(
                db,
                user_id=test_user.id,
                event=DividendEvent.create(
                    payment_date=date(2026, 4, 5),
                    asset_identifier=asset,
                    gross_amount=Decimal("25.00"),
                    withholding_tax=wht,
                    currency="SGD",
                ),
                accounts=accts,
            )
    uid, aid = uuid4(), uuid4()
    stub = lambda val: type("_Stub", (), {"scalar": lambda _s, _q: _async_val(val)})()
    for val, match in (
        (None, f"account {aid} not found"),
        (SimpleNamespace(name="Loan", type=AccountType.LIABILITY, is_active=True), "account Loan must be ASSET"),
        (
            SimpleNamespace(name="Closed Cash", type=AccountType.ASSET, is_active=False),
            "account Closed Cash is inactive",
        ),
    ):
        with pytest.raises(InvestmentAccountingValidationError, match=match):
            await svc._get_account(stub(val), uid, aid, AccountType.ASSET)
    with pytest.raises(InvestmentAccountingValidationError, match="position MISSING not found"):
        await svc._get_position(stub(None), user_id=uid, account_id=aid, asset_identifier="MISSING")


async def _async_val(val):
    return val


async def test_AC_portfolio_2427_1_balance_sheet_disposition_honors_trade_account_and_skips_duplicate_trade(
    db: AsyncSession, test_user, svc: InvestmentAccountingService, chart: dict[str, Account]
):
    default_loan = await _get_or_create_default_counter_account(
        db, test_user.id, AccountType.LIABILITY, "SGD", name="Loans Payable (SGD)"
    )
    default_loan.name = "OCBC Home Mortgage (SGD)"
    await db.flush()
    db.info.pop("_default_account_cache", None)
    resolved_again = await _get_or_create_default_counter_account(
        db, test_user.id, AccountType.LIABILITY, "SGD", name="Loans Payable (SGD)"
    )
    custom_broker = Account(
        user_id=test_user.id, name="IBKR Brokerage Assets", code="1325", type=AccountType.ASSET, currency="SGD"
    )
    buy_stmt_txn = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2026, 2, 10),
        amount=Decimal("1005.00"),
        currency="SGD",
        direction=TransactionDirection.OUT,
        description="IBKR Buy 10 VWRA",
        source_documents={},
        dedup_hash="stmt_ibkr_buy_vwra",
    )
    db.add_all([custom_broker, buy_stmt_txn])
    await db.flush()
    suggestion = ClassificationSuggestion(
        atomic_txn_id=buy_stmt_txn.id,
        category=TransactionCategory.INVESTMENT_TRADE.value,
        confidence=92,
        account_id=custom_broker.id,
        applied=False,
        corrected=True,
    )
    intent, counter_account, category, _ = await _balance_sheet_disposition_for(
        db, test_user.id, buy_stmt_txn, suggestion
    )
    await svc.post_buy(
        db,
        user_id=test_user.id,
        order=_order(date(2026, 2, 10), "VWRA", Decimal("10"), Decimal("100.00"), fees=Decimal("5.00")),
        accounts=TradeAccounts(cash=chart["cash"].id, investment=custom_broker.id),
    )
    duplicate = await _balance_sheet_disposition_for(db, test_user.id, buy_stmt_txn, suggestion)
    assert (default_loan.code, resolved_again.id, intent, counter_account.id, category, duplicate) == (
        "2210",
        default_loan.id,
        EconomicIntent.INVESTMENT_PURCHASE,
        custom_broker.id,
        TransactionCategory.INVESTMENT_TRADE.value,
        None,
    )
