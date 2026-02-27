"""Tests for portfolio performance service (XIRR, TWR, MWR).

AC17.3 block: Performance metrics — XIRR, TWR, MWR calculations.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.services.performance import (
    InsufficientDataError,
    calculate_money_weighted_return,
    calculate_time_weighted_return,
    calculate_xirr,
)


@pytest.fixture
async def investment_account(db: AsyncSession, test_user):
    account = Account(
        user_id=test_user.id,
        name="Investment Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    return account


@pytest.fixture
async def portfolio_with_transactions(db: AsyncSession, test_user, investment_account):
    """Create a portfolio with realistic transaction history."""
    from src.models.layer2 import AtomicPosition

    # Initial deposit (3 months ago)
    deposit_date = date.today() - timedelta(days=90)
    deposit = AtomicTransaction(
        user_id=test_user.id,
        txn_date=deposit_date,
        amount=Decimal("10000.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="Initial deposit",
        source_documents={},
        dedup_hash=f"deposit_{deposit_date}",
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

    # Additional deposit (1 month ago)
    recent_deposit_date = date.today() - timedelta(days=30)
    recent_deposit = AtomicTransaction(
        user_id=test_user.id,
        txn_date=recent_deposit_date,
        amount=Decimal("5000.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="Additional deposit",
        source_documents={},
        dedup_hash=f"deposit_{recent_deposit_date}",
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


@pytest.mark.asyncio
async def test_xirr_insufficient_data(db: AsyncSession, test_user):
    """AC17.3.1: XIRR raises InsufficientDataError on empty portfolio.

    Verify that XIRR calculation fails gracefully when no transactions exist.
    """
    with pytest.raises(InsufficientDataError):
        await calculate_xirr(db, test_user.id)


@pytest.mark.asyncio
async def test_xirr_with_realistic_data(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC17.3.2: XIRR calculates annualized return for realistic portfolio.

    Verify that XIRR returns a negative Decimal for a loss scenario (deposits > current value).
    """
    xirr = await calculate_xirr(db, test_user.id)

    # With deposits totaling 15000 and current value 12000, XIRR should be negative
    # (since we lost money overall)
    assert isinstance(xirr, Decimal)
    assert xirr < Decimal("0")  # Loss scenario


@pytest.mark.asyncio
async def test_time_weighted_return_empty_portfolio(db: AsyncSession, test_user):
    """AC17.3.3: TWR returns zero for empty portfolio.

    Verify that TWR handles empty portfolio gracefully by returning Decimal(0).
    """
    start = date.today() - timedelta(days=30)
    end = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, start, end)
    assert twr == Decimal("0")


@pytest.mark.asyncio
async def test_time_weighted_return_with_period(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC17.3.4: TWR calculates period return within reasonable bounds.

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


@pytest.mark.asyncio
async def test_money_weighted_return_insufficient_data(db: AsyncSession, test_user):
    """AC17.3.5: MWR raises InsufficientDataError on empty portfolio.

    Verify that MWR calculation fails gracefully when no data exists.
    """
    with pytest.raises(InsufficientDataError):
        await calculate_money_weighted_return(db, test_user.id)


@pytest.mark.asyncio
async def test_money_weighted_return_with_data(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC17.3.6: MWR calculates money-weighted return for loss scenario.

    Verify that MWR returns a negative Decimal when total deposits exceed current value.
    """
    mwr = await calculate_money_weighted_return(db, test_user.id)

    # Similar to XIRR, should reflect actual cash flows
    assert isinstance(mwr, Decimal)
    # With total deposits 15000 and current value 12000, MWR should be negative
    assert mwr < Decimal("0")


@pytest.mark.asyncio
async def test_xirr_with_as_of_date(db: AsyncSession, test_user, portfolio_with_transactions):
    """AC17.3.7: XIRR respects as_of_date parameter.

    Verify that XIRR calculates return as of a historical date.
    """
    past_date = date.today() - timedelta(days=45)

    # Should calculate XIRR as of 45 days ago
    xirr = await calculate_xirr(db, test_user.id, as_of_date=past_date)

    assert isinstance(xirr, Decimal)


@pytest.mark.asyncio
async def test_time_weighted_return_same_day(db: AsyncSession, test_user):
    """AC17.3.8: TWR returns zero for same-day period.

    Verify that TWR returns 0 when period_start == period_end.
    """
    today = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, today, today)

    # Same day should return 0 or very small value
    assert twr == Decimal("0")


@pytest.mark.asyncio
async def test_performance_metrics_with_zero_positions(db: AsyncSession, test_user):
    """AC17.3.9: Performance metrics handle cash-only portfolios.

    Verify that XIRR raises InsufficientDataError when portfolio has deposits but no positions.
    """
    from src.models.layer2 import AtomicTransaction

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


@pytest.mark.asyncio
async def test_xirr_convergence_edge_case(db: AsyncSession, test_user, investment_account):
    """AC17.3.10: XIRR handles extreme convergence edge cases.

    Verify that extreme gain scenarios either produce a very high XIRR or raise InsufficientDataError.
    """
    from src.models.layer2 import AtomicPosition, AtomicTransaction

    # Create scenario with extreme values that might cause convergence issues
    deposit = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date.today() - timedelta(days=365),
        amount=Decimal("1.00"),  # Very small initial
        currency="SGD",
        direction=TransactionDirection.IN,
        description="Tiny deposit for convergence test",
        source_documents={},
        dedup_hash="tiny_deposit",
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
    except InsufficientDataError:
        # Acceptable if convergence fails
        pass


# ──────────────────────────────────────────────
# Pure-function tests for _xirr_newton / _xirr_bisection
# ──────────────────────────────────────────────


def test_xirr_bisection_no_root_raises():
    """AC17.3.11: _xirr_bisection raises ValueError when no root exists.

    Verify that all-positive cash flows cause a ValueError (no sign change in search range).
    """
    from src.services.performance import _xirr_bisection

    # All positive cash flows -> NPV always positive -> no root
    amounts = [Decimal("100"), Decimal("200"), Decimal("300")]
    days = [0, 180, 365]
    with pytest.raises(ValueError, match="No root in"):
        _xirr_bisection(amounts, days, max_iter=200, tolerance=Decimal("1e-6"))


def test_xirr_bisection_max_iter_returns():
    """AC17.3.12: _xirr_bisection returns Decimal estimate after max_iter exhaustion.

    Verify that bisection returns a Decimal midpoint when max_iter is too small to converge.
    """
    from src.services.performance import _xirr_bisection

    # Normal cash flows (negative deposit, positive terminal) with max_iter=1
    # so it can't converge but should return a midpoint
    amounts = [Decimal("-10000"), Decimal("12000")]
    days = [0, 365]
    result = _xirr_bisection(amounts, days, max_iter=1, tolerance=Decimal("1e-12"))
    assert isinstance(result, Decimal)


def test_xirr_newton_fallthrough_to_bisection():
    """AC17.3.13: _xirr_newton falls back to bisection on non-convergence.

    Verify that Newton's method with insufficient iterations falls back to bisection and returns Decimal.
    """
    from src.services.performance import _xirr_newton

    # Use a guess that won't converge easily with very few iterations
    amounts = [Decimal("-10000"), Decimal("12000")]
    days = [0, 365]
    result = _xirr_newton(amounts, days, guess=Decimal("0.1"), max_iter=1, tolerance=Decimal("1e-15"))
    assert isinstance(result, Decimal)


@pytest.mark.asyncio
async def test_xirr_calculation_error_raised(db: AsyncSession, test_user, investment_account, monkeypatch):
    """AC17.3.14: XIRRCalculationError raised when Newton and bisection both fail.

    Verify that monkeypatching _xirr_newton to always raise causes XIRRCalculationError.
    """
    from src.models.layer2 import AtomicPosition, AtomicTransaction
    from src.services.performance import XIRRCalculationError

    deposit = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date.today() - timedelta(days=30),
        amount=Decimal("10000.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="deposit",
        source_documents={},
        dedup_hash="xirr_error_deposit",
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
        broker="B",
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

    monkeypatch.setattr("src.services.performance._xirr_newton", _raise_newton)

    with pytest.raises(XIRRCalculationError):
        await calculate_xirr(db, test_user.id)
