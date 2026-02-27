"""Tests for portfolio performance service (XIRR, TWR, MWR)."""

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
    """XIRR should raise error when no transactions exist."""
    with pytest.raises(InsufficientDataError):
        await calculate_xirr(db, test_user.id)


@pytest.mark.asyncio
async def test_xirr_with_realistic_data(db: AsyncSession, test_user, portfolio_with_transactions):
    """XIRR should calculate annualized return correctly."""
    xirr = await calculate_xirr(db, test_user.id)

    # With deposits totaling 15000 and current value 12000, XIRR should be negative
    # (since we lost money overall)
    assert isinstance(xirr, Decimal)
    assert xirr < Decimal("0")  # Loss scenario


@pytest.mark.asyncio
async def test_time_weighted_return_empty_portfolio(db: AsyncSession, test_user):
    """TWR should return 0 for empty portfolio."""
    start = date.today() - timedelta(days=30)
    end = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, start, end)
    assert twr == Decimal("0")


@pytest.mark.asyncio
async def test_time_weighted_return_with_period(db: AsyncSession, test_user, portfolio_with_transactions):
    """TWR should calculate period return correctly."""
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
    """MWR should raise error when no data exists."""
    with pytest.raises(InsufficientDataError):
        await calculate_money_weighted_return(db, test_user.id)


@pytest.mark.asyncio
async def test_money_weighted_return_with_data(db: AsyncSession, test_user, portfolio_with_transactions):
    """MWR should calculate money-weighted return correctly."""
    mwr = await calculate_money_weighted_return(db, test_user.id)

    # Similar to XIRR, should reflect actual cash flows
    assert isinstance(mwr, Decimal)
    # With total deposits 15000 and current value 12000, MWR should be negative
    assert mwr < Decimal("0")


@pytest.mark.asyncio
async def test_xirr_with_as_of_date(db: AsyncSession, test_user, portfolio_with_transactions):
    """XIRR should respect as_of_date parameter."""
    past_date = date.today() - timedelta(days=45)

    # Should calculate XIRR as of 45 days ago
    xirr = await calculate_xirr(db, test_user.id, as_of_date=past_date)

    assert isinstance(xirr, Decimal)


@pytest.mark.asyncio
async def test_time_weighted_return_same_day(db: AsyncSession, test_user):
    """TWR should handle same-day period gracefully."""
    today = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, today, today)

    # Same day should return 0 or very small value
    assert twr == Decimal("0")


@pytest.mark.asyncio
async def test_performance_metrics_with_zero_positions(db: AsyncSession, test_user):
    """Performance metrics should handle portfolios with only cash."""
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
    """XIRR should handle edge cases where IRR calculation might not converge."""
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
