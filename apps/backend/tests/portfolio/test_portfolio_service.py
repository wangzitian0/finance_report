"""AC17.1/AC17.2/AC17.5: Portfolio service tests — holdings, realized/unrealized PnL, price updates."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.models.market_data import FxRate
from src.models.portfolio import MarketDataOverride, PriceSource
from src.schemas.portfolio import PriceUpdateRequest
from src.services.portfolio import (
    AssetNotFoundError,
    InvalidDateRangeError,
    PortfolioNotFoundError,
    PortfolioService,
)


@pytest.fixture
async def svc():
    return PortfolioService()


@pytest.fixture
async def account(db: AsyncSession, test_user):
    acct = Account(
        user_id=test_user.id,
        name="Test Investment",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(acct)
    await db.flush()
    return acct


@pytest.fixture
async def active_position(db: AsyncSession, test_user, account):
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="AAPL",
        quantity=Decimal("100"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=60),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)
    await db.flush()
    return pos


@pytest.fixture
async def atomic_snapshot(db: AsyncSession, test_user):
    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="AAPL",
        broker="Test Broker",
        quantity=Decimal("100"),
        market_value=Decimal("12000.00"),
        currency="SGD",
        sector="Technology",
        geography="US",
        asset_type="stock",
        dedup_hash="aapl_svc_test",
        source_documents={},
    )
    db.add(atom)
    await db.flush()
    return atom


# ──────────────────────────────────────────────
# get_holdings  (Lines 57–173)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_holdings_happy_path(db, test_user, svc, active_position, atomic_snapshot):
    """AC17.1.1: Holdings happy path returns correct market value, cost basis, and classification.

    Verify that get_holdings returns enriched HoldingResponse with PnL and sector data.
    """
    holdings = await svc.get_holdings(db, test_user.id)
    assert len(holdings) == 1
    h = holdings[0]
    assert h.asset_identifier == "AAPL"
    assert h.market_value == Decimal("12000.00")
    assert h.cost_basis == Decimal("10000.00")
    assert h.unrealized_pnl == Decimal("2000.00")
    assert h.sector == "Technology"
    assert h.geography == "US"
    assert h.asset_type == "stock"
    assert h.account_name == "Test Investment"


@pytest.mark.asyncio
async def test_get_holdings_no_positions_raises(db, test_user, svc):
    """AC17.1.2: Holdings on empty portfolio raises PortfolioNotFoundError.

    Verify that get_holdings raises PortfolioNotFoundError when user has no positions.
    """
    with pytest.raises(PortfolioNotFoundError):
        await svc.get_holdings(db, test_user.id)


@pytest.mark.asyncio
async def test_get_holdings_include_disposed(db, test_user, svc, account, atomic_snapshot):
    """AC17.1.3: Disposed positions included only when include_disposed=True."""
    disposed = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="AAPL",
        quantity=Decimal("50"),
        cost_basis=Decimal("5000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=90),
        disposal_date=date.today() - timedelta(days=10),
        status=PositionStatus.DISPOSED,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(disposed)
    await db.flush()

    # Without include_disposed -> raises (no ACTIVE positions)
    with pytest.raises(PortfolioNotFoundError):
        await svc.get_holdings(db, test_user.id, include_disposed=False)

    # With include_disposed -> returns the disposed position
    holdings = await svc.get_holdings(db, test_user.id, include_disposed=True)
    assert len(holdings) == 1
    assert holdings[0].status == PositionStatus.DISPOSED


@pytest.mark.asyncio
async def test_get_holdings_fx_conversion(db, test_user, svc, account):
    """AC17.1.4: FX conversion applied when position currency != base currency (SGD)."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="MSFT",
        quantity=Decimal("50"),
        cost_basis=Decimal("5000.00"),
        currency="USD",
        acquisition_date=date.today() - timedelta(days=30),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)

    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="MSFT",
        broker="Broker",
        quantity=Decimal("50"),
        market_value=Decimal("6000.00"),
        currency="USD",
        dedup_hash="msft_fx_test",
        source_documents={},
    )
    db.add(atom)

    fx = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.35"),
        rate_date=date.today(),
        source="test",
    )
    db.add(fx)

    fx_acq = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.30"),
        rate_date=date.today() - timedelta(days=30),
        source="test",
    )
    db.add(fx_acq)
    await db.flush()

    holdings = await svc.get_holdings(db, test_user.id)
    assert len(holdings) == 1
    h = holdings[0]
    # market_value: 6000 * 1.35 = 8100
    assert h.market_value == Decimal("8100.00")
    # cost_basis: 5000 * 1.30 = 6500
    assert h.cost_basis == Decimal("6500.00")
    assert h.currency == "SGD"


@pytest.mark.asyncio
async def test_get_holdings_zero_cost_basis(db, test_user, svc, account):
    """AC17.1.5: Zero cost basis -> unrealized_pnl_percent = 0."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="FREE",
        quantity=Decimal("10"),
        cost_basis=Decimal("0.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=10),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.AVGCOST,
    )
    db.add(pos)

    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="FREE",
        broker="Broker",
        quantity=Decimal("10"),
        market_value=Decimal("500.00"),
        currency="SGD",
        dedup_hash="free_zero_cost",
        source_documents={},
    )
    db.add(atom)
    await db.flush()

    holdings = await svc.get_holdings(db, test_user.id)
    assert len(holdings) == 1
    assert holdings[0].unrealized_pnl_percent == Decimal("0.00")


@pytest.mark.asyncio
async def test_get_holdings_no_atomic_for_classification(db, test_user, svc, account):
    """AC17.1.6: No atomic position for user -> classification fields stay None."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="NOCLASS",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=10),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)

    # Atomic with matching asset_identifier but for a DIFFERENT user
    other_user_atom = AtomicPosition(
        user_id=uuid4(),
        snapshot_date=date.today(),
        asset_identifier="NOCLASS",
        broker="B",
        quantity=Decimal("10"),
        market_value=Decimal("1200.00"),
        currency="SGD",
        dedup_hash="noclass_other_user",
        source_documents={},
        sector="Other",
    )
    db.add(other_user_atom)

    # But we do need a price source for this user -> use override
    override = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="NOCLASS",
        price_date=date.today(),
        price=Decimal("120.00"),
        currency="SGD",
        source=PriceSource.MANUAL,
    )
    db.add(override)
    await db.flush()

    holdings = await svc.get_holdings(db, test_user.id)
    assert len(holdings) == 1
    assert holdings[0].asset_type is None
    assert holdings[0].sector is None
    assert holdings[0].geography is None


# ──────────────────────────────────────────────
# calculate_realized_pnl  (Lines 175–297)
# ──────────────────────────────────────────────


@pytest.fixture
async def disposed_position(db, test_user, account):
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="GOOG",
        quantity=Decimal("20"),
        cost_basis=Decimal("3000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=120),
        disposal_date=date.today() - timedelta(days=5),
        status=PositionStatus.DISPOSED,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)

    # Atomic snapshot at disposal date for price lookup
    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today() - timedelta(days=5),
        asset_identifier="GOOG",
        broker="Broker",
        quantity=Decimal("20"),
        market_value=Decimal("4000.00"),
        currency="SGD",
        dedup_hash="goog_disposed",
        source_documents={},
    )
    db.add(atom)
    await db.flush()
    return pos


@pytest.mark.asyncio
async def test_realized_pnl_happy_path(db, test_user, svc, disposed_position):
    """AC17.2.1: Realized PnL happy path returns correct total and details.

    Verify that calculate_realized_pnl returns correct PnL for disposed positions.
    """
    start = date.today() - timedelta(days=30)
    end = date.today()
    result = await svc.calculate_realized_pnl(db, test_user.id, start, end)
    assert result.positions_count == 1
    # disposal_value = 20 * (4000/20) = 4000, cost = 3000 -> pnl = 1000
    assert result.total_realized_pnl == Decimal("1000.00")
    assert len(result.details) == 1
    assert result.details[0]["asset_identifier"] == "GOOG"


@pytest.mark.asyncio
async def test_realized_pnl_invalid_date_range(db, test_user, svc):
    """AC17.2.2: Invalid date range raises InvalidDateRangeError.

    Verify that start_date > end_date triggers InvalidDateRangeError.
    """
    with pytest.raises(InvalidDateRangeError):
        await svc.calculate_realized_pnl(db, test_user.id, date.today(), date.today() - timedelta(days=1))


@pytest.mark.asyncio
async def test_realized_pnl_no_disposed(db, test_user, svc):
    """AC17.2.3: No disposed positions -> returns zero response."""
    result = await svc.calculate_realized_pnl(db, test_user.id, date.today() - timedelta(days=30), date.today())
    assert result.total_realized_pnl == Decimal("0")
    assert result.positions_count == 0
    assert result.details == []


@pytest.mark.asyncio
async def test_realized_pnl_zero_cost(db, test_user, svc, account):
    """AC17.2.4: Zero cost -> realized_pnl_percent = 0."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="ZERO",
        quantity=Decimal("10"),
        cost_basis=Decimal("0.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=60),
        disposal_date=date.today() - timedelta(days=3),
        status=PositionStatus.DISPOSED,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)

    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today() - timedelta(days=3),
        asset_identifier="ZERO",
        broker="B",
        quantity=Decimal("10"),
        market_value=Decimal("500.00"),
        currency="SGD",
        dedup_hash="zero_cost_disposed",
        source_documents={},
    )
    db.add(atom)
    await db.flush()

    result = await svc.calculate_realized_pnl(db, test_user.id, date.today() - timedelta(days=30), date.today())
    assert result.total_realized_pnl == Decimal("500.00")
    assert result.total_realized_pnl_percent == Decimal("0.00")


@pytest.mark.asyncio
async def test_realized_pnl_fx_conversion(db, test_user, svc, account):
    """AC17.2.5: Disposed position in non-base currency triggers FX conversion."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="TSLA",
        quantity=Decimal("5"),
        cost_basis=Decimal("1000.00"),
        currency="USD",
        acquisition_date=date.today() - timedelta(days=90),
        disposal_date=date.today() - timedelta(days=2),
        status=PositionStatus.DISPOSED,
        cost_basis_method=CostBasisMethod.LIFO,
    )
    db.add(pos)

    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today() - timedelta(days=2),
        asset_identifier="TSLA",
        broker="B",
        quantity=Decimal("5"),
        market_value=Decimal("1500.00"),
        currency="USD",
        dedup_hash="tsla_disposed_fx",
        source_documents={},
    )
    db.add(atom)

    fx_disposal = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.35"),
        rate_date=date.today() - timedelta(days=2),
        source="test",
    )
    db.add(fx_disposal)

    fx_acq = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.30"),
        rate_date=date.today() - timedelta(days=90),
        source="test",
    )
    db.add(fx_acq)
    await db.flush()

    result = await svc.calculate_realized_pnl(db, test_user.id, date.today() - timedelta(days=30), date.today())
    assert result.positions_count == 1
    # disposal: 1500 * 1.35 = 2025, cost: 1000 * 1.30 = 1300 -> pnl = 725
    assert result.total_realized_pnl == Decimal("725.00")


# ──────────────────────────────────────────────
# calculate_unrealized_pnl  (Lines 299–408)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unrealized_pnl_happy_path(db, test_user, svc, active_position, atomic_snapshot):
    """AC17.2.6: Unrealized PnL happy path returns correct totals.

    Verify that calculate_unrealized_pnl returns correct market value, cost basis, and PnL.
    """
    result = await svc.calculate_unrealized_pnl(db, test_user.id)
    assert result.holdings_count == 1
    assert result.total_market_value == Decimal("12000.00")
    assert result.total_cost_basis == Decimal("10000.00")
    assert result.total_unrealized_pnl == Decimal("2000.00")
    assert len(result.details) == 1


@pytest.mark.asyncio
async def test_unrealized_pnl_no_positions(db, test_user, svc):
    """AC17.2.7: Unrealized PnL on empty portfolio raises PortfolioNotFoundError.

    Verify that calculate_unrealized_pnl raises when user has no active positions.
    """
    with pytest.raises(PortfolioNotFoundError):
        await svc.calculate_unrealized_pnl(db, test_user.id)


@pytest.mark.asyncio
async def test_unrealized_pnl_zero_cost(db, test_user, svc, account):
    """AC17.2.8: Zero cost -> unrealized_pnl_percent in details = 0."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="GIFT",
        quantity=Decimal("5"),
        cost_basis=Decimal("0.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=30),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.AVGCOST,
    )
    db.add(pos)

    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="GIFT",
        broker="B",
        quantity=Decimal("5"),
        market_value=Decimal("250.00"),
        currency="SGD",
        dedup_hash="gift_unrealized",
        source_documents={},
    )
    db.add(atom)
    await db.flush()

    result = await svc.calculate_unrealized_pnl(db, test_user.id)
    assert result.total_unrealized_pnl_percent == Decimal("0.00")
    assert result.details[0]["unrealized_pnl_percent"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_unrealized_pnl_fx_conversion(db, test_user, svc, account):
    """AC17.2.9: FX conversion for unrealized PnL."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="NVDA",
        quantity=Decimal("10"),
        cost_basis=Decimal("2000.00"),
        currency="USD",
        acquisition_date=date.today() - timedelta(days=45),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)

    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="NVDA",
        broker="B",
        quantity=Decimal("10"),
        market_value=Decimal("2500.00"),
        currency="USD",
        dedup_hash="nvda_unrealized_fx",
        source_documents={},
    )
    db.add(atom)

    fx_now = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.35"),
        rate_date=date.today(),
        source="test",
    )
    db.add(fx_now)

    fx_acq = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.30"),
        rate_date=date.today() - timedelta(days=45),
        source="test",
    )
    db.add(fx_acq)
    await db.flush()

    result = await svc.calculate_unrealized_pnl(db, test_user.id)
    # market: 2500 * 1.35 = 3375, cost: 2000 * 1.30 = 2600 -> pnl = 775
    assert result.total_market_value == Decimal("3375.00")
    assert result.total_cost_basis == Decimal("2600.00")
    assert result.total_unrealized_pnl == Decimal("775.00")


# ──────────────────────────────────────────────
# get_portfolio_summary  (Lines 485–540)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portfolio_summary_happy(db, test_user, svc, active_position, atomic_snapshot):
    """AC17.1.7: Portfolio summary happy path returns correct counts and totals.

    Verify that get_portfolio_summary returns accurate summary with PnL.
    """
    summary = await svc.get_portfolio_summary(db, test_user.id)
    assert summary.holdings_count == 1
    assert summary.active_positions_count == 1
    assert summary.disposed_positions_count == 0
    assert summary.total_market_value == Decimal("12000.00")
    assert summary.total_cost_basis == Decimal("10000.00")
    assert summary.net_pnl == Decimal("2000.00")
    assert summary.currency == "SGD"


@pytest.mark.asyncio
async def test_portfolio_summary_with_disposed(db, test_user, svc, account, atomic_snapshot):
    """AC17.1.8: Summary includes both active and disposed positions."""
    active = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="AAPL",
        quantity=Decimal("100"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=60),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(active)
    disposed = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="AAPL",
        quantity=Decimal("50"),
        cost_basis=Decimal("5000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=120),
        disposal_date=date.today() - timedelta(days=10),
        status=PositionStatus.DISPOSED,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(disposed)
    await db.flush()
    summary = await svc.get_portfolio_summary(db, test_user.id)
    assert summary.active_positions_count == 1
    assert summary.disposed_positions_count == 1
    assert summary.holdings_count == 2


@pytest.mark.asyncio
async def test_portfolio_summary_zero_cost(db, test_user, svc, account):
    """AC17.1.9: Zero total cost -> net_pnl_percent = 0."""
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="FREEBIE",
        quantity=Decimal("1"),
        cost_basis=Decimal("0.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=5),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)

    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="FREEBIE",
        broker="B",
        quantity=Decimal("1"),
        market_value=Decimal("100.00"),
        currency="SGD",
        dedup_hash="freebie_summary",
        source_documents={},
    )
    db.add(atom)
    await db.flush()

    summary = await svc.get_portfolio_summary(db, test_user.id)
    assert summary.net_pnl_percent == Decimal("0.00")


# ──────────────────────────────────────────────
# update_market_prices  (Lines 410–483)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_prices_happy(db, test_user, svc, active_position):
    """AC17.5.1: Update market prices happy path creates override.

    Verify that update_market_prices creates a MarketDataOverride record.
    """
    updates = [
        PriceUpdateRequest(
            asset_identifier="AAPL",
            price_date=date.today(),
            price=Decimal("155.00"),
            currency="SGD",
        )
    ]
    results = await svc.update_market_prices(db, test_user.id, updates)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].created_at is not None


@pytest.mark.asyncio
async def test_update_prices_asset_not_found(db, test_user, svc):
    """AC17.5.2: Update prices for non-existent asset returns failure.

    Verify that update_market_prices returns success=False for unknown assets.
    """
    updates = [
        PriceUpdateRequest(
            asset_identifier="NOPE",
            price_date=date.today(),
            price=Decimal("99.00"),
            currency="SGD",
        )
    ]
    results = await svc.update_market_prices(db, test_user.id, updates)
    assert len(results) == 1
    assert results[0].success is False
    assert "not found" in results[0].message


# ──────────────────────────────────────────────
# _get_latest_price  (Lines 542–599)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_latest_price_override(db, test_user, svc, active_position):
    """AC17.5.3: Override price takes precedence over atomic position price."""
    override = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="AAPL",
        price_date=date.today(),
        price=Decimal("200.00"),
        currency="SGD",
        source=PriceSource.MANUAL,
    )
    db.add(override)
    await db.flush()

    price = await svc._get_latest_price(db, active_position, date.today(), test_user.id)
    assert price == Decimal("200.00")


@pytest.mark.asyncio
async def test_get_latest_price_from_atomic(db, test_user, svc, active_position, atomic_snapshot):
    """AC17.5.4: Per-unit price = market_value / quantity from atomic position."""
    price = await svc._get_latest_price(db, active_position, date.today(), test_user.id)
    # 12000 / 100 = 120
    assert price == Decimal("120")


@pytest.mark.asyncio
async def test_get_latest_price_zero_quantity(db, test_user, svc, active_position):
    """AC17.5.5: Quantity == 0 -> return market_value directly."""
    atom = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="AAPL",
        broker="B",
        quantity=Decimal("0"),
        market_value=Decimal("999.00"),
        currency="SGD",
        dedup_hash="aapl_zero_qty",
        source_documents={},
    )
    db.add(atom)
    await db.flush()

    price = await svc._get_latest_price(db, active_position, date.today(), test_user.id)
    assert price == Decimal("999.00")


@pytest.mark.asyncio
async def test_get_latest_price_no_data(db, test_user, svc, active_position):
    """AC17.5.6: No price data -> AssetNotFoundError."""
    with pytest.raises(AssetNotFoundError):
        await svc._get_latest_price(db, active_position, date.today(), test_user.id)


# ──────────────────────────────────────────────
# _get_latest_atomic  (Lines 601–628)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_latest_atomic_returns_latest(db, test_user, svc):
    """AC17.5.7: _get_latest_atomic returns the most recent snapshot.

    Verify that when multiple snapshots exist, the latest by date is returned.
    """
    old = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today() - timedelta(days=30),
        asset_identifier="TEST",
        broker="B",
        quantity=Decimal("10"),
        market_value=Decimal("100.00"),
        currency="SGD",
        sector="Old",
        dedup_hash="test_old",
        source_documents={},
    )
    new = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="TEST",
        broker="B",
        quantity=Decimal("10"),
        market_value=Decimal("200.00"),
        currency="SGD",
        sector="New",
        dedup_hash="test_new",
        source_documents={},
    )
    db.add_all([old, new])
    await db.flush()

    result = await svc._get_latest_atomic(db, "TEST", test_user.id)
    assert result is not None
    assert result.sector == "New"


@pytest.mark.asyncio
async def test_get_latest_atomic_none(db, test_user, svc):
    """AC17.5.8: _get_latest_atomic returns None when no snapshots exist.

    Verify that _get_latest_atomic returns None for unknown asset.
    """
    result = await svc._get_latest_atomic(db, "NOPE", test_user.id)
    assert result is None
