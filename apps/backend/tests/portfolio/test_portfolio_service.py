"""Portfolio service tests - Holdings, P&L, price updates, summary calculations."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.layer3 import ManagedPosition, PositionStatus
from src.services import fx
from src.services.portfolio import (
    AssetNotFoundError,
    InsufficientDataError,
    InvalidDateRangeError,
    PortfolioError,
    PortfolioService,
    PortfolioNotFoundError,
)


@pytest.fixture
async def portfolio_service(db: AsyncSession):
    """Create portfolio service instance."""
    return PortfolioService()


@pytest.fixture
async def test_user_id():
    """Test user ID."""
    return uuid4()


@pytest.fixture
async def portfolio_account(db: AsyncSession, test_user_id):
    """Create test brokerage account."""
    account = Account(
        user_id=test_user_id,
        name="Test Brokerage Account",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.fixture
async def positions(db: AsyncSession, test_user_id, portfolio_account):
    """Create multiple positions for testing."""
    positions = []

    # Position 1: AAPL, 10 shares, cost basis 1500
    pos1 = ManagedPosition(
        user_id=test_user_id,
        account_id=portfolio_account.id,
        asset_identifier="AAPL",
        quantity=Decimal("10.0"),
        cost_basis=Decimal("1500.00"),
        acquisition_date=date(2024, 1, 15),
        status=PositionStatus.ACTIVE,
        currency="USD",
    )
    db.add(pos1)

    # Position 2: MSFT, 5 shares, cost basis 600
    pos2 = ManagedPosition(
        user_id=test_user_id,
        account_id=portfolio_account.id,
        asset_identifier="MSFT",
        quantity=Decimal("5.0"),
        cost_basis=Decimal("600.00"),
        acquisition_date=date(2024, 2, 1),
        status=PositionStatus.ACTIVE,
        currency="USD",
    )
    db.add(pos2)

    # Position 3: GOOGL, disposed (quantity 0)
    pos3 = ManagedPosition(
        user_id=test_user_id,
        account_id=portfolio_account.id,
        asset_identifier="GOOGL",
        quantity=Decimal("0.0"),
        cost_basis=Decimal("2000.00"),
        acquisition_date=date(2024, 1, 10),
        disposal_date=date(2024, 1, 14),
        status=PositionStatus.DISPOSED,
        currency="USD",
    )
    db.add(pos3)

    await db.commit()
    positions.extend([pos1, pos2, pos3])

    # Add historical atomic positions (snapshots)
    atomic1 = AtomicPosition(
        user_id=test_user_id,
        snapshot_date=date(2024, 1, 20),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("10.0"),
        market_value=Decimal("1600.00"),
        currency="USD",
        dedup_hash="hash_aapl1",
        source_documents={},
    )
    db.add(atomic1)

    atomic2 = AtomicPosition(
        user_id=test_user_id,
        snapshot_date=date(2024, 2, 10),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("10.0"),
        market_value=Decimal("1700.00"),
        currency="USD",
        dedup_hash="hash_aapl2",
        source_documents={},
    )
    db.add(atomic2)

    # Add transaction for AAPL
    txn = AtomicTransaction(
        user_id=test_user_id,
        txn_date=date(2024, 1, 20),
        amount=Decimal("1600.00"),
        direction=TransactionDirection.IN,
        description="AAPL dividend",
        reference="DIV-001",
        currency="USD",
        dedup_hash="txn_div_aapl_001",
        source_documents={},
    )
    db.add(txn)

    await db.commit()
    return positions


@pytest.mark.asyncio
async def test_get_holdings_empty(db: AsyncSession, test_user_id, portfolio_account, portfolio_service):
    """Test get_holdings returns empty list when no positions exist."""
    holdings = await portfolio_service.get_holdings(db, test_user_id)

    assert holdings == []
    assert len(holdings) == 0


@pytest.mark.asyncio
async def test_get_holdings_single_position(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test get_holdings returns single active position."""
    holdings = await portfolio_service.get_holdings(db, test_user_id)

    assert len(holdings) == 2  # Only active positions (AAPL, MSFT), not disposed
    assert holdings[0].asset_identifier == "AAPL"
    assert holdings[0].quantity == Decimal("10.000000")
    assert holdings[0].account_name == "Test Brokerage Account"


@pytest.mark.asyncio
async def test_get_holdings_multiple_positions(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test get_holdings returns all active positions."""
    holdings = await portfolio_service.get_holdings(db, test_user_id)

    assert len(holdings) == 2
    asset_identifiers = {h.asset_identifier for h in holdings}
    assert asset_identifiers == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_get_holdings_include_disposed(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test get_holdings includes disposed positions when requested."""
    holdings = await portfolio_service.get_holdings(db, test_user_id, include_disposed=True)

    assert len(holdings) == 3  # All positions including disposed
    assert any(h.asset_identifier == "GOOGL" for h in holdings)


@pytest.mark.asyncio
async def test_get_holdings_with_account_filter(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test get_holdings filters by account."""
    # Create another account
    other_account = Account(
        user_id=test_user_id,
        name="Other Broker",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(other_account)
    await db.commit()

    holdings = await portfolio_service.get_holdings(db, test_user_id, account_id=portfolio_account.id)

    assert len(holdings) == 2
    assert all(h.account_id == portfolio_account.id for h in holdings)


@pytest.mark.asyncio
async def test_get_holdings_with_account_filter_excludes_other_account(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test get_holdings with account_id only returns positions from that account."""
    # Create another account with positions
    other_account = Account(
        user_id=test_user_id,
        name="Other Broker",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(other_account)
    await db.commit()

    other_pos = ManagedPosition(
        user_id=test_user_id,
        account_id=other_account.id,
        asset_identifier="TSLA",
        quantity=Decimal("5.0"),
        cost_basis=Decimal("1000.00"),
        acquisition_date=date(2024, 1, 1),
        status=PositionStatus.ACTIVE,
        currency="USD",
    )
    db.add(other_pos)
    await db.commit()

    holdings = await portfolio_service.get_holdings(db, test_user_id, account_id=portfolio_account.id)

    assert len(holdings) == 2
    assert all(h.account_id == portfolio_account.id for h in holdings)


@pytest.mark.asyncio
async def test_get_holdings_with_as_of_date(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test get_holdings evaluates positions as of a specific date."""
    # AAPL's latest atomic position is on 2024-02-10 with market value 1700
    holdings = await portfolio_service.get_holdings(db, test_user_id, as_of_date=date(2024, 2, 5))

    assert len(holdings) == 2
    # Should have AAPL's value as of 2024-02-05 (between 2024-01-20 and 2024-02-10)
    aapl = next(h for h in holdings if h.asset_identifier == "AAPL")
    assert aapl.market_value == Decimal("1600.00")  # Value from 2024-01-20


@pytest.mark.asyncio
async def test_get_holdings_multi_currency(db: AsyncSession, test_user_id, portfolio_service):
    """Test get_holdings handles multi-currency portfolios with FX conversion."""
    # Create USD account
    usd_account = Account(
        user_id=test_user_id,
        name="USD Account",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(usd_account)
    await db.flush()

    # Create SGD account
    sgd_account = Account(
        user_id=test_user_id,
        name="SGD Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(sgd_account)
    await db.flush()

    # USD position
    usd_pos = ManagedPosition(
        user_id=test_user_id,
        account_id=usd_account.id,
        asset_identifier="AAPL",
        quantity=Decimal("10.0"),
        cost_basis=Decimal("1500.00"),
        acquisition_date=date(2024, 1, 1),
        status=PositionStatus.ACTIVE,
        currency="USD",
    )
    db.add(usd_pos)

    # SGD position
    sgd_pos = ManagedPosition(
        user_id=test_user_id,
        account_id=sgd_account.id,
        asset_identifier="TSLA",
        quantity=Decimal("5.0"),
        cost_basis=Decimal("1000.00"),
        acquisition_date=date(2024, 1, 1),
        status=PositionStatus.ACTIVE,
        currency="SGD",
    )
    db.add(sgd_pos)

    await db.commit()

    # Mock FX rate: 1 USD = 1.35 SGD
    async def mock_convert(amount, from_currency, to_currency, as_of_date):
        if from_currency == "USD" and to_currency == "SGD":
            return amount * Decimal("1.35")
        elif from_currency == "SGD" and to_currency == "USD":
            return amount / Decimal("1.35")
        return amount

    # Patch fx.convert_amount
    original_convert = fx.convert_amount
    fx.convert_amount = mock_convert

    try:
        holdings = await portfolio_service.get_holdings(db, test_user_id)

        assert len(holdings) == 2
        # Both should be in SGD after FX conversion
        for h in holdings:
            assert h.currency == "SGD"
    finally:
        fx.convert_amount = original_convert


@pytest.mark.asyncio
async def test_get_holdings_unknown_account(db: AsyncSession, test_user_id, portfolio_service):
    """Test get_holdings returns empty when account_id doesn't belong to user."""
    fake_account_id = uuid4()

    with pytest.raises(PortfolioNotFoundError):
        await portfolio_service.get_holdings(db, test_user_id, account_id=fake_account_id)


@pytest.mark.asyncio
async def test_get_holdings_no_positions_for_user(db: AsyncSession, portfolio_service):
    """Test get_holdings returns empty when user has no positions."""
    fake_user_id = uuid4()

    holdings = await portfolio_service.get_holdings(db, fake_user_id)

    assert holdings == []


@pytest.mark.asyncio
async def test_get_holdings_unrealized_pnl_calculation(
    db: AsyncSession, test_user_id, portfolio_account, portfolio_service
):
    """Test unrealized P&L is calculated correctly."""
    # Add atomic positions for market values
    aapl_atomic = AtomicPosition(
        user_id=test_user_id,
        snapshot_date=date.today(),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("10.0"),
        market_value=Decimal("1700.00"),
        currency="USD",
        dedup_hash="hash_aapl_today",
        source_documents={},
    )
    db.add(aapl_atomic)

    msft_atomic = AtomicPosition(
        user_id=test_user_id,
        snapshot_date=date.today(),
        asset_identifier="MSFT",
        broker="Test Broker",
        quantity=Decimal("5.0"),
        market_value=Decimal("500.00"),
        currency="USD",
        dedup_hash="hash_msft_today",
        source_documents={},
    )
    db.add(msft_atomic)

    await db.commit()

    holdings = await portfolio_service.get_holdings(db, test_user_id)

    # AAPL: Cost 1500, Value 1700 = Unrealized P&L 200
    # MSFT: Cost 600, Value 500 = Unrealized P&L -100
    assert len(holdings) == 2

    aapl = next(h for h in holdings if h.asset_identifier == "AAPL")
    assert aapl.unrealized_pnl == Decimal("200.00")
    assert aapl.unrealized_pnl_percent == Decimal("13.33")

    msft = next(h for h in holdings if h.asset_identifier == "MSFT")
    assert msft.unrealized_pnl == Decimal("-100.00")
    assert msft.unrealized_pnl_percent == Decimal("-16.67")


@pytest.mark.asyncio
async def test_get_holdings_asset_classification_fields(
    db: AsyncSession, test_user_id, portfolio_account, portfolio_service
):
    """Test asset classification fields (asset_type, sector, geography) are populated."""
    # Add atomic positions with classification
    aapl_atomic = AtomicPosition(
        user_id=test_user_id,
        snapshot_date=date.today(),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("10.0"),
        market_value=Decimal("1700.00"),
        currency="US",
        asset_type="stock",
        sector="Technology",
        geography="US",
        dedup_hash="hash_aapl_class",
        source_documents={},
    )
    db.add(aapl_atomic)

    await db.commit()

    holdings = await portfolio_service.get_holdings(db, test_user_id)

    assert len(holdings) == 1
    aapl = holdings[0]
    assert aapl.asset_type == "stock"
    assert aapl.sector == "Technology"
    assert aapl.geography == "US"


@pytest.mark.asyncio
async def test_get_holdings_disposed_position_not_included_by_default(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test disposed positions are not included by default."""
    holdings = await portfolio_service.get_holdings(db, test_user_id)

    assert len(holdings) == 2  # Only active positions
    assert not any(h.asset_identifier == "GOOGL" for h in holdings)


@pytest.mark.asyncio
async def test_get_holdings_disposed_position_included_when_flagged(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test disposed positions are included when include_disposed=True."""
    holdings = await portfolio_service.get_holdings(db, test_user_id, include_disposed=True)

    assert len(holdings) == 3  # All positions including disposed
    assert any(h.asset_identifier == "GOOGL" for h in holdings)


@pytest.mark.asyncio
async def test_get_holdings_disposed_position_has_zero_quantity(
    db: AsyncSession, test_user_id, portfolio_account, positions, portfolio_service
):
    """Test disposed positions have quantity 0."""
    holdings = await portfolio_service.get_holdings(db, test_user_id, include_disposed=True)

    disposed = next(h for h in holdings if h.asset_identifier == "GOOGL")
    assert disposed.quantity == Decimal("0.000000")
    assert disposed.status == PositionStatus.DISPOSED
