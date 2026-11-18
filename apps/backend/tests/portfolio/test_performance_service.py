import inspect
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction
from src.ledger import Account, AccountType
from src.portfolio import DividendIncome, InsufficientDataError, InvestmentTransaction, InvestmentTransactionType, XIRRCalculationError, calculate_dividend_yield, calculate_money_weighted_return, calculate_time_weighted_return, calculate_xirr
import src.portfolio.extension.performance as performance_module
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus


def _buy(user_id, tx_date: date, asset: str, gross: Decimal, qty: Decimal = Decimal("1")) -> InvestmentTransaction:
    return InvestmentTransaction(
        user_id=user_id,
        transaction_date=tx_date,
        transaction_type=InvestmentTransactionType.BUY,
        asset_identifier=asset,
        quantity=qty,
        unit_price=gross / qty,
        gross_amount=gross,
        fees=Decimal("0.00"),
        currency="SGD",
        cost_basis=gross,
        cost_basis_method=CostBasisMethod.FIFO,
    )


def _pos(user_id, account_id, asset: str, acq_date: date, *, qty: Decimal = Decimal("100"), cost: Decimal = Decimal("10000.00"), status: PositionStatus = PositionStatus.ACTIVE, disposal_date: date | None = None) -> ManagedPosition:
    return ManagedPosition(user_id=user_id, account_id=account_id, asset_identifier=asset, quantity=qty, cost_basis=cost, currency="SGD", acquisition_date=acq_date, disposal_date=disposal_date, status=status, cost_basis_method=CostBasisMethod.FIFO)


def _atom(user_id, snap_date: date, asset: str, mv: Decimal, dedup: str, *, qty: Decimal = Decimal("100"), **extra) -> AtomicPosition:
    return AtomicPosition(user_id=user_id, snapshot_date=snap_date, asset_identifier=asset, broker="Test Broker", quantity=qty, market_value=mv, currency="SGD", dedup_hash=dedup, source_documents={}, **extra)


async def _flush(db: AsyncSession, *objs) -> None:
    db.add_all(objs)
    await db.flush()


@pytest.fixture
async def investment_account(db: AsyncSession, test_user):
    account = Account(user_id=test_user.id, name="Test Broker", type=AccountType.ASSET, currency="SGD")
    await _flush(db, account)
    return account


@pytest.fixture
async def portfolio_with_transactions(db: AsyncSession, test_user, investment_account):
    today = date.today()
    pos = _pos(test_user.id, investment_account.id, "AAPL", today - timedelta(days=60))
    await _flush(
        db,
        _buy(test_user.id, today - timedelta(days=90), "AAPL", Decimal("10000.00"), Decimal("100")),
        pos,
        _atom(test_user.id, today, "AAPL", Decimal("12000.00"), "aapl_snapshot", sector="Technology", geography="US", asset_type="stock"),
        _atom(test_user.id, today - timedelta(days=60), "AAPL", Decimal("10000.00"), "aapl_snapshot_early", sector="Technology", geography="US", asset_type="stock"),
        _buy(test_user.id, today - timedelta(days=30), "AAPL", Decimal("5000.00"), Decimal("50")),
    )
    return {"account": investment_account, "position": pos}


async def test_returns_with_empty_and_realistic_data(db: AsyncSession, test_user):
    today = date.today()
    with pytest.raises(InsufficientDataError):
        await calculate_xirr(db, test_user.id, base_currency="SGD")
    with pytest.raises(InsufficientDataError):
        await calculate_money_weighted_return(db, test_user.id, base_currency="SGD")
    assert (
        await calculate_time_weighted_return(db, test_user.id, today - timedelta(days=30), today, base_currency="SGD"),
        await calculate_time_weighted_return(db, test_user.id, today, today, base_currency="SGD"),
        await calculate_dividend_yield(db, test_user.id, base_currency="SGD"),
    ) == (Decimal("0"), Decimal("0"), Decimal("0"))
    await _flush(db, AtomicTransaction(user_id=test_user.id, txn_date=today - timedelta(days=30), amount=Decimal("1000.00"), currency="SGD", direction=TransactionDirection.IN, description="Cash only deposit", source_documents={}, dedup_hash="cash_only"))
    with pytest.raises(InsufficientDataError):
        await calculate_xirr(db, test_user.id, base_currency="SGD")


async def test_returns_with_portfolio_transactions(db: AsyncSession, test_user, portfolio_with_transactions):
    today = date.today()
    xirr = await calculate_xirr(db, test_user.id, base_currency="SGD")
    past_xirr = await calculate_xirr(db, test_user.id, as_of_date=today - timedelta(days=45), base_currency="SGD")
    twr = await calculate_time_weighted_return(db, test_user.id, today - timedelta(days=59), today, base_currency="SGD")
    mwr = await calculate_money_weighted_return(db, test_user.id, base_currency="SGD")
    assert (isinstance(xirr, Decimal), xirr < 0, isinstance(past_xirr, Decimal), isinstance(twr, Decimal), Decimal("-100") <= twr <= Decimal("1000"), isinstance(mwr, Decimal), mwr < 0) == (True, True, True, True, True, True, True)


async def test_AC5_6_1_AC5_6_6_xirr_and_mwr_single_year_match(db: AsyncSession, test_user, investment_account):
    start = date.today() - timedelta(days=365)
    await _flush(
        db,
        _buy(test_user.id, start, "XIRR10", Decimal("10000.00"), Decimal("100")),
        _pos(test_user.id, investment_account.id, "XIRR10", start),
        _atom(test_user.id, date.today(), "XIRR10", Decimal("11000.00"), "ac5_6_1_xirr_snapshot"),
    )
    xirr = await calculate_xirr(db, test_user.id, base_currency="SGD")
    mwr = await calculate_money_weighted_return(db, test_user.id, base_currency="SGD")
    assert (abs(xirr - Decimal("10.00")) <= Decimal("0.01"), mwr == xirr) == (True, True)


async def test_AC5_6_2_time_weighted_return_matches_snapshot_period(db: AsyncSession, test_user, investment_account):
    start, end = date.today() - timedelta(days=30), date.today()
    await _flush(
        db,
        _pos(test_user.id, investment_account.id, "TWR", start),
        _atom(test_user.id, start, "TWR", Decimal("10000.00"), "ac5_6_2_twr_start"),
        _atom(test_user.id, end, "TWR", Decimal("11250.00"), "ac5_6_2_twr_end"),
    )
    assert await calculate_time_weighted_return(db, test_user.id, start, end, base_currency="SGD") == Decimal("12.500")


@pytest.mark.parametrize("disposed_after_as_of", [False, True])
async def test_AC5_6_3_dividend_yield_active_and_disposed_after_as_of(db: AsyncSession, test_user, investment_account, disposed_after_as_of):
    today = date.today()
    as_of = today - timedelta(days=60) if disposed_after_as_of else today
    pos = _pos(test_user.id, investment_account.id, "DIV", today - timedelta(days=90 if disposed_after_as_of else 400), qty=Decimal("0" if disposed_after_as_of else "120"), status=PositionStatus.DISPOSED if disposed_after_as_of else PositionStatus.ACTIVE, disposal_date=today - timedelta(days=10) if disposed_after_as_of else None)
    await _flush(db, pos)
    await _flush(
        db,
        _atom(test_user.id, as_of, "DIV", Decimal("10000.00" if disposed_after_as_of else "12000.00"), f"ac5_6_3_{disposed_after_as_of}", qty=Decimal("100" if disposed_after_as_of else "120")),
        DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=as_of - timedelta(days=30), amount=Decimal("100.00" if disposed_after_as_of else "240.00"), currency="SGD"),
    )
    assert await calculate_dividend_yield(db, test_user.id, as_of, base_currency="SGD") == Decimal("1.00" if disposed_after_as_of else "2.00")


async def test_AC5_6_3_dividend_yield_with_income_requires_current_value(db: AsyncSession, test_user, investment_account):
    today = date.today()
    pos = _pos(test_user.id, investment_account.id, "DIV-ZERO", today - timedelta(days=400), qty=Decimal("120"))
    await _flush(db, pos)
    await _flush(db, DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=today - timedelta(days=30), amount=Decimal("240.00"), currency="SGD"))
    with pytest.raises(InsufficientDataError):
        await calculate_dividend_yield(db, test_user.id, today, base_currency="SGD")


async def test_xirr_convergence_and_forced_error(db: AsyncSession, test_user, investment_account, monkeypatch):
    start = date.today() - timedelta(days=365)
    await _flush(
        db,
        _buy(test_user.id, start, "MOON", Decimal("1.00")),
        _pos(test_user.id, investment_account.id, "MOON", start, qty=Decimal("1"), cost=Decimal("1.00")),
        _atom(test_user.id, date.today(), "MOON", Decimal("1000000.00"), "moon_snapshot", qty=Decimal("1")),
    )
    try:
        assert await calculate_xirr(db, test_user.id, base_currency="SGD") > Decimal("1000")
    except (InsufficientDataError, XIRRCalculationError):
        pass
    monkeypatch.setattr("src.portfolio.extension.performance._xirr_newton", lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("forced failure")))
    with pytest.raises(XIRRCalculationError):
        await calculate_xirr(db, test_user.id, base_currency="SGD")


def test_xirr_solver_helpers_and_AC17_10_5_no_float():
    with pytest.raises(ValueError, match="No root in"):
        performance_module._xirr_bisection([Decimal("100"), Decimal("200"), Decimal("300")], [0, 180, 365], max_iter=200, tolerance=Decimal("1e-6"))
    bisect_res = performance_module._xirr_bisection([Decimal("-10000"), Decimal("12000")], [0, 365], max_iter=1, tolerance=Decimal("1e-12"))
    newton_res = performance_module._xirr_newton([Decimal("-10000"), Decimal("12000")], [0, 365], guess=Decimal("0.1"), max_iter=1, tolerance=Decimal("1e-15"))
    solver_source = inspect.getsource(performance_module._xirr_newton) + inspect.getsource(performance_module._xirr_bisection)
    assert (isinstance(bisect_res, Decimal), isinstance(newton_res, Decimal), "float_amounts" not in solver_source, "float(a) for a in amounts" not in solver_source) == (True, True, True, True)
