"""Tests for portfolio performance service (XIRR, TWR, MWR).

AC17.3 block: Performance metrics — XIRR, TWR, MWR calculations.
AC5.6.1 AC5.6.2 AC5.6.3 AC5.6.6: Portfolio return and yield metric calculations.
"""

import inspect
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import TransactionDirection
from src.extraction.orm.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.ledger import Account, AccountType
from src.portfolio import (
    DividendIncome,
    InsufficientDataError,
    InvestmentTransaction,
    InvestmentTransactionType,
    XIRRCalculationError,
    calculate_dividend_yield,
    calculate_money_weighted_return,
    calculate_time_weighted_return,
    calculate_xirr,
)


@pytest.fixture
async def investment_account(db: AsyncSession, test_user):
    # Name matches the AtomicPosition.broker string used throughout this file's
    # fixtures/tests -- point-in-time lookups now key by (asset_identifier,
    # broker) via Account.name (#1791 follow-up), mirroring how
    # _get_or_create_broker_account always names the account after the broker.
    account = Account(
        user_id=test_user.id,
        name="Test Broker",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    return account


def _buy_transaction(
    *,
    user_id,
    transaction_date: date,
    asset_identifier: str,
    gross_amount: Decimal,
    quantity: Decimal = Decimal("1"),
) -> InvestmentTransaction:
    return InvestmentTransaction(
        user_id=user_id,
        transaction_date=transaction_date,
        transaction_type=InvestmentTransactionType.BUY,
        asset_identifier=asset_identifier,
        quantity=quantity,
        unit_price=gross_amount / quantity,
        gross_amount=gross_amount,
        fees=Decimal("0.00"),
        currency="SGD",
        cost_basis=gross_amount,
        cost_basis_method=CostBasisMethod.FIFO,
    )


@pytest.fixture
async def portfolio_with_transactions(db: AsyncSession, test_user, investment_account):
    """Create a portfolio with realistic transaction history."""
    from src.extraction.orm.layer2 import AtomicPosition

    # Initial buy (3 months ago)
    deposit_date = date.today() - timedelta(days=90)
    deposit = _buy_transaction(
        user_id=test_user.id,
        transaction_date=deposit_date,
        asset_identifier="AAPL",
        gross_amount=Decimal("10000.00"),
        quantity=Decimal("100"),
    )
    db.add(deposit)

    # Position opened (2 months ago)
    position_date = date.today() - timedelta(days=60)
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="AAPL",
        quantity=Decimal("100"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=position_date,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)

    # Current position snapshot (today)
    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("100"),
        market_value=Decimal("12000.00"),  # 20% gain
        currency="SGD",
        sector="Technology",
        geography="US",
        asset_type="stock",
        dedup_hash="aapl_snapshot",
        source_documents={},
    )
    db.add(atomic)

    # Early snapshot at position open date for historical queries
    early_atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today() - timedelta(days=60),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("100"),
        market_value=Decimal("10000.00"),
        currency="SGD",
        sector="Technology",
        geography="US",
        asset_type="stock",
        dedup_hash="aapl_snapshot_early",
        source_documents={},
    )
    db.add(early_atomic)

    # Additional buy (1 month ago)
    recent_deposit_date = date.today() - timedelta(days=30)
    recent_deposit = _buy_transaction(
        user_id=test_user.id,
        transaction_date=recent_deposit_date,
        asset_identifier="AAPL",
        gross_amount=Decimal("5000.00"),
        quantity=Decimal("50"),
    )
    db.add(recent_deposit)

    await db.flush()
    return {
        "account": investment_account,
        "position": position,
        "initial_deposit": Decimal("10000.00"),
        "additional_deposit": Decimal("5000.00"),
        "current_value": Decimal("12000.00"),
    }


async def test_xirr_insufficient_data(db: AsyncSession, test_user):
    """AC17.3.1: XIRR raises InsufficientDataError on empty portfolio.

    Verify that XIRR calculation fails gracefully when no transactions exist.
    """
    with pytest.raises(InsufficientDataError):
        await calculate_xirr(db, test_user.id)


async def test_xirr_with_realistic_data(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC-portfolio.performance.1: AC17.2.1: XIRR calculates annualized return for realistic portfolio.

    Verify that XIRR returns a negative Decimal for a loss scenario (deposits > current value).
    """
    xirr = await calculate_xirr(db, test_user.id)

    # With deposits totaling 15000 and current value 12000, XIRR should be negative
    # (since we lost money overall)
    assert isinstance(xirr, Decimal)
    assert xirr < Decimal("0")  # Loss scenario


async def test_AC5_6_1_xirr_matches_single_year_excel_case(db: AsyncSession, test_user, investment_account):
    """AC-portfolio.metrics.1: AC5.6.1: XIRR is within 0.01 percentage points of a one-year Excel case."""
    from src.extraction.orm.layer2 import AtomicPosition

    start = date.today() - timedelta(days=365)
    db.add(
        _buy_transaction(
            user_id=test_user.id,
            transaction_date=start,
            asset_identifier="XIRR10",
            gross_amount=Decimal("10000.00"),
            quantity=Decimal("100"),
        )
    )
    db.add(
        ManagedPosition(
            user_id=test_user.id,
            account_id=investment_account.id,
            asset_identifier="XIRR10",
            quantity=Decimal("100"),
            cost_basis=Decimal("10000.00"),
            currency="SGD",
            acquisition_date=start,
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    db.add(
        AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date.today(),
            asset_identifier="XIRR10",
            broker="Test Broker",
            quantity=Decimal("100"),
            market_value=Decimal("11000.00"),
            currency="SGD",
            dedup_hash="ac5_6_1_xirr_snapshot",
            source_documents={},
        )
    )
    await db.flush()

    xirr = await calculate_xirr(db, test_user.id)

    assert abs(xirr - Decimal("10.00")) <= Decimal("0.01")


async def test_time_weighted_return_empty_portfolio(db: AsyncSession, test_user):
    """AC17.3.3: TWR returns zero for empty portfolio.

    Verify that TWR handles empty portfolio gracefully by returning Decimal(0).
    """
    start = date.today() - timedelta(days=30)
    end = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, start, end)
    assert twr == Decimal("0")


async def test_time_weighted_return_with_period(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC-portfolio.performance.2: AC17.2.2 (canonical; AC17.3.4 was a duplicate restatement): TWR calculates period return within reasonable bounds.

    Verify that TWR returns a valid percentage for a period with transactions.
    """
    start = date.today() - timedelta(days=59)
    end = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, start, end)

    # Should return a valid percentage
    assert isinstance(twr, Decimal)
    # TWR can be positive or negative depending on data
    assert twr >= Decimal("-100")  # Not worse than -100%
    assert twr <= Decimal("1000")  # Not more than 1000%


async def test_AC5_6_2_time_weighted_return_matches_snapshot_period(
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-portfolio.metrics.2: AC5.6.2: TWR computes the exact period return from start/end snapshots."""
    from src.extraction.orm.layer2 import AtomicPosition

    start = date.today() - timedelta(days=30)
    end = date.today()
    db.add(
        ManagedPosition(
            user_id=test_user.id,
            account_id=investment_account.id,
            asset_identifier="TWR",
            quantity=Decimal("100"),
            cost_basis=Decimal("10000.00"),
            currency="SGD",
            acquisition_date=start,
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    db.add_all(
        [
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=start,
                asset_identifier="TWR",
                broker="Test Broker",
                quantity=Decimal("100"),
                market_value=Decimal("10000.00"),
                currency="SGD",
                dedup_hash="ac5_6_2_twr_start",
                source_documents={},
            ),
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=end,
                asset_identifier="TWR",
                broker="Test Broker",
                quantity=Decimal("100"),
                market_value=Decimal("11250.00"),
                currency="SGD",
                dedup_hash="ac5_6_2_twr_end",
                source_documents={},
            ),
        ]
    )
    await db.flush()

    twr = await calculate_time_weighted_return(db, test_user.id, start, end)

    assert twr == Decimal("12.500")


async def test_money_weighted_return_insufficient_data(db: AsyncSession, test_user):
    """AC-portfolio.allocation.4: AC17.3.5: MWR raises InsufficientDataError on empty portfolio.

    Verify that MWR calculation fails gracefully when no data exists.
    """
    with pytest.raises(InsufficientDataError):
        await calculate_money_weighted_return(db, test_user.id)


async def test_money_weighted_return_with_data(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC-portfolio.performance.3: AC17.2.3 (canonical; AC17.3.6 was a duplicate restatement): MWR calculates money-weighted return for loss scenario.

    Verify that MWR returns a negative Decimal when total deposits exceed current value.
    """
    mwr = await calculate_money_weighted_return(db, test_user.id)

    # Similar to XIRR, should reflect actual cash flows
    assert isinstance(mwr, Decimal)
    # With total deposits 15000 and current value 12000, MWR should be negative
    assert mwr < Decimal("0")


async def test_AC5_6_3_dividend_yield_uses_trailing_dividends_over_current_value(
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-portfolio.metrics.3: AC5.6.3: Dividend yield equals annual dividends divided by current value."""
    from src.extraction.orm.layer2 import AtomicPosition

    today = date.today()
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="DIV",
        quantity=Decimal("120"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=today - timedelta(days=400),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()
    db.add(
        AtomicPosition(
            user_id=test_user.id,
            snapshot_date=today,
            asset_identifier="DIV",
            broker="Test Broker",
            quantity=Decimal("120"),
            market_value=Decimal("12000.00"),
            currency="SGD",
            dedup_hash="ac5_6_3_dividend_snapshot",
            source_documents={},
        )
    )
    db.add(
        DividendIncome(
            user_id=test_user.id,
            position_id=position.id,
            payment_date=today - timedelta(days=30),
            amount=Decimal("240.00"),
            currency="SGD",
        )
    )
    await db.flush()

    dividend_yield = await calculate_dividend_yield(db, test_user.id, today)

    assert dividend_yield == Decimal("2.00")


async def test_AC5_6_3_dividend_yield_counts_position_disposed_after_as_of_date(
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-portfolio.metrics.5 (#1791 follow-up): a position held as of
    as_of_date must count toward that date's portfolio value even though it
    has since been disposed -- ManagedPosition.status reflects *today*, not
    as_of_date, so point-in-time inclusion must come from the snapshot
    quantity on that date (mirrors holdings.py:_get_snapshot_holdings), not
    from the position's current status."""
    from src.extraction.orm.layer2 import AtomicPosition

    today = date.today()
    as_of_date = today - timedelta(days=60)

    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="SOLD",
        quantity=Decimal("0"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=today - timedelta(days=90),
        disposal_date=today - timedelta(days=10),
        status=PositionStatus.DISPOSED,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()

    # Snapshot as of as_of_date: the position was still held then.
    db.add(
        AtomicPosition(
            user_id=test_user.id,
            snapshot_date=as_of_date,
            asset_identifier="SOLD",
            broker="Test Broker",
            quantity=Decimal("100"),
            market_value=Decimal("10000.00"),
            currency="SGD",
            dedup_hash="ac5_6_3_disposed_after_as_of_date",
            source_documents={},
        )
    )
    db.add(
        DividendIncome(
            user_id=test_user.id,
            position_id=position.id,
            payment_date=as_of_date - timedelta(days=30),
            amount=Decimal("100.00"),
            currency="SGD",
        )
    )
    await db.flush()

    dividend_yield = await calculate_dividend_yield(db, test_user.id, as_of_date)

    assert dividend_yield == Decimal("1.00")


async def test_AC5_6_3_dividend_yield_empty_portfolio_returns_zero(db: AsyncSession, test_user):
    """AC5.6.3: Dividend yield returns zero when no dividends or holdings exist."""
    dividend_yield = await calculate_dividend_yield(db, test_user.id)

    assert dividend_yield == Decimal("0")


async def test_AC5_6_3_dividend_yield_with_income_requires_current_value(
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC5.6.3: Dividend yield refuses positive income with zero current value."""
    today = date.today()
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="DIV-ZERO",
        quantity=Decimal("120"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=today - timedelta(days=400),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()
    db.add(
        DividendIncome(
            user_id=test_user.id,
            position_id=position.id,
            payment_date=today - timedelta(days=30),
            amount=Decimal("240.00"),
            currency="SGD",
        )
    )
    await db.flush()

    with pytest.raises(InsufficientDataError):
        await calculate_dividend_yield(db, test_user.id, today)


async def test_AC5_6_6_money_weighted_return_matches_xirr_for_single_cashflow(
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-portfolio.metrics.4: AC5.6.6: MWR matches XIRR for a single cash-flow portfolio."""
    from src.extraction.orm.layer2 import AtomicPosition

    start = date.today() - timedelta(days=365)
    db.add(
        _buy_transaction(
            user_id=test_user.id,
            transaction_date=start,
            asset_identifier="MWR",
            gross_amount=Decimal("10000.00"),
            quantity=Decimal("100"),
        )
    )
    db.add(
        ManagedPosition(
            user_id=test_user.id,
            account_id=investment_account.id,
            asset_identifier="MWR",
            quantity=Decimal("100"),
            cost_basis=Decimal("10000.00"),
            currency="SGD",
            acquisition_date=start,
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    db.add(
        AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date.today(),
            asset_identifier="MWR",
            broker="Test Broker",
            quantity=Decimal("100"),
            market_value=Decimal("11000.00"),
            currency="SGD",
            dedup_hash="ac5_6_6_mwr_snapshot",
            source_documents={},
        )
    )
    await db.flush()

    xirr = await calculate_xirr(db, test_user.id)
    mwr = await calculate_money_weighted_return(db, test_user.id)

    assert mwr == xirr


async def test_xirr_with_as_of_date(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC-portfolio.allocation.5: AC17.3.7: XIRR respects as_of_date parameter.

    Verify that XIRR calculates return as of a historical date.
    """
    past_date = date.today() - timedelta(days=45)

    # Should calculate XIRR as of 45 days ago
    xirr = await calculate_xirr(db, test_user.id, as_of_date=past_date)

    assert isinstance(xirr, Decimal)


async def test_time_weighted_return_same_day(db: AsyncSession, test_user):
    """AC-portfolio.allocation.6: AC17.3.8: TWR returns zero for same-day period.

    Verify that TWR returns 0 when period_start == period_end.
    """
    today = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, today, today)

    # Same day should return 0 or very small value
    assert twr == Decimal("0")


async def test_performance_metrics_with_zero_positions(db: AsyncSession, test_user):
    """AC-portfolio.allocation.7: AC17.3.9: Performance metrics handle cash-only portfolios.

    Verify that XIRR raises InsufficientDataError when portfolio has deposits but no positions.
    """
    from src.extraction.orm.layer2 import AtomicTransaction

    # Add cash deposit but no positions
    deposit = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date.today() - timedelta(days=30),
        amount=Decimal("1000.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="Cash only deposit",
        source_documents={},
        dedup_hash="cash_only",
    )
    db.add(deposit)
    await db.flush()

    # XIRR with only deposits and no growth should be error or 0
    with pytest.raises(InsufficientDataError):
        await calculate_xirr(db, test_user.id)


async def test_xirr_convergence_edge_case(db: AsyncSession, test_user, investment_account):
    """AC-portfolio.allocation.8: AC17.3.10: XIRR handles extreme convergence edge cases.

    Verify that extreme gain scenarios either produce a very high XIRR or raise InsufficientDataError.
    """
    from src.extraction.orm.layer2 import AtomicPosition

    # Create scenario with extreme values that might cause convergence issues
    deposit = _buy_transaction(
        user_id=test_user.id,
        transaction_date=date.today() - timedelta(days=365),
        asset_identifier="MOON",
        gross_amount=Decimal("1.00"),
    )
    db.add(deposit)

    # Position with huge gain
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="MOON",
        quantity=Decimal("1"),
        cost_basis=Decimal("1.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=365),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)

    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="MOON",
        broker="Test",
        quantity=Decimal("1"),
        market_value=Decimal("1000000.00"),  # 1M% gain
        currency="SGD",
        dedup_hash="moon_snapshot",
        source_documents={},
    )
    db.add(atomic)
    await db.flush()

    # Should either calculate or raise appropriate error
    try:
        xirr = await calculate_xirr(db, test_user.id)
        # If it succeeds, should be extremely high
        assert xirr > Decimal("1000")  # Over 1000% annualized
    except (InsufficientDataError, XIRRCalculationError):
        # Acceptable if convergence fails or data is insufficient
        pass


# ──────────────────────────────────────────────
# Pure-function tests for _xirr_newton / _xirr_bisection
# ──────────────────────────────────────────────


def test_xirr_bisection_no_root_raises():
    """AC-portfolio.allocation.9: AC17.3.11: _xirr_bisection raises ValueError when no root exists.

    Verify that all-positive cash flows cause a ValueError (no sign change in search range).
    """
    from src.portfolio.extension.performance import _xirr_bisection

    # All positive cash flows -> NPV always positive -> no root
    amounts = [Decimal("100"), Decimal("200"), Decimal("300")]
    days = [0, 180, 365]
    with pytest.raises(ValueError, match="No root in"):
        _xirr_bisection(amounts, days, max_iter=200, tolerance=Decimal("1e-6"))


def test_AC17_10_5_xirr_solver_does_not_float_monetary_cashflows():
    """AC-portfolio.report-schedule.5: AC17.10.5: XIRR internals do not convert monetary Decimal cash flows to float."""
    import src.portfolio.extension.performance as performance_module

    solver_source = inspect.getsource(performance_module._xirr_newton) + inspect.getsource(
        performance_module._xirr_bisection
    )

    assert "float_amounts" not in solver_source
    assert "float(a) for a in amounts" not in solver_source


def test_xirr_bisection_max_iter_returns():
    """AC-portfolio.allocation.10: AC17.3.12: _xirr_bisection returns Decimal estimate after max_iter exhaustion.

    Verify that bisection returns a Decimal midpoint when max_iter is too small to converge.
    """
    from src.portfolio.extension.performance import _xirr_bisection

    # Normal cash flows (negative deposit, positive terminal) with max_iter=1
    # so it can't converge but should return a midpoint
    amounts = [Decimal("-10000"), Decimal("12000")]
    days = [0, 365]
    result = _xirr_bisection(amounts, days, max_iter=1, tolerance=Decimal("1e-12"))
    assert isinstance(result, Decimal)


def test_xirr_newton_fallthrough_to_bisection():
    """AC-portfolio.allocation.11: AC17.3.13: _xirr_newton falls back to bisection on non-convergence.

    Verify that Newton's method with insufficient iterations falls back to bisection and returns Decimal.
    """
    from src.portfolio.extension.performance import _xirr_newton

    # Use a guess that won't converge easily with very few iterations
    amounts = [Decimal("-10000"), Decimal("12000")]
    days = [0, 365]
    result = _xirr_newton(amounts, days, guess=Decimal("0.1"), max_iter=1, tolerance=Decimal("1e-15"))
    assert isinstance(result, Decimal)


async def test_xirr_calculation_error_raised(db: AsyncSession, test_user, investment_account, monkeypatch):
    """AC-portfolio.allocation.12: AC17.3.14: XIRRCalculationError raised when Newton and bisection both fail.

    Verify that monkeypatching _xirr_newton to always raise causes XIRRCalculationError.
    """
    from src.extraction.orm.layer2 import AtomicPosition
    from src.portfolio import XIRRCalculationError

    deposit = _buy_transaction(
        user_id=test_user.id,
        transaction_date=date.today() - timedelta(days=30),
        asset_identifier="ERR",
        gross_amount=Decimal("10000.00"),
    )
    db.add(deposit)

    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="ERR",
        quantity=Decimal("1"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=30),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)

    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="ERR",
        broker="Test Broker",
        quantity=Decimal("1"),
        market_value=Decimal("11000.00"),
        currency="SGD",
        dedup_hash="xirr_error_snap",
        source_documents={},
    )
    db.add(atomic)
    await db.flush()

    def _raise_newton(*args, **kwargs):
        raise ValueError("forced failure")

    monkeypatch.setattr("src.portfolio.extension.performance._xirr_newton", _raise_newton)

    with pytest.raises(XIRRCalculationError):
        await calculate_xirr(db, test_user.id)
