"""Portfolio performance metrics service - XIRR, TWR, MWR calculations."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logger import get_logger
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.layer3 import ManagedPosition, PositionStatus
from src.services import fx

logger = get_logger(__name__)


class PerformanceError(Exception):
    """Base exception for performance calculation errors."""

    pass


class InsufficientDataError(PerformanceError):
    """Raised when insufficient data for performance calculation."""

    pass


class XIRRCalculationError(PerformanceError):
    """Raised when XIRR calculation fails to converge."""

    pass


async def _batch_latest_atomic_positions(
    db: AsyncSession,
    user_id: UUID,
    asset_identifiers: list[str],
    as_of_date: date,
) -> dict[str, AtomicPosition]:
    """
    Batch-fetch the latest AtomicPosition for each asset_identifier in a single query.

    Uses a window function (ROW_NUMBER) to find the most recent snapshot per asset,
    avoiding the N+1 pattern of querying one asset at a time.

    Args:
        db: Database session
        user_id: User ID
        asset_identifiers: List of asset identifiers to fetch
        as_of_date: Fetch snapshots on or before this date

    Returns:
        dict mapping asset_identifier → latest AtomicPosition
    """
    if not asset_identifiers:
        return {}

    # Subquery: rank snapshots per asset by date descending
    row_num = (
        func.row_number()
        .over(
            partition_by=AtomicPosition.asset_identifier,
            order_by=AtomicPosition.snapshot_date.desc(),
        )
        .label("rn")
    )

    subq = (
        select(AtomicPosition.id, row_num)
        .where(
            AtomicPosition.user_id == user_id,
            AtomicPosition.asset_identifier.in_(asset_identifiers),
            AtomicPosition.snapshot_date <= as_of_date,
        )
        .subquery()
    )

    # Join back to get full AtomicPosition rows where rn == 1
    query = select(AtomicPosition).join(subq, AtomicPosition.id == subq.c.id).where(subq.c.rn == 1)

    result = await db.execute(query)
    rows = result.scalars().all()

    return {row.asset_identifier: row for row in rows}


async def calculate_xirr(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,
) -> Decimal:
    """
    Calculate XIRR (Extended Internal Rate of Return) for portfolio.

    XIRR is the annualized rate of return that makes NPV of all cash flows equal to zero.
    Formula: Sum of (cash_flow_i / (1 + xirr)^(days_i / 365)) = 0

    Args:
        db: Database session
        user_id: User ID
        as_of_date: Calculate as of this date (default: today)

    Returns:
        Decimal: Annualized return as percentage (e.g., 15.5 for 15.5%)

    Raises:
        InsufficientDataError: Need at least one cash flow and one position
        XIRRCalculationError: XIRR calculation failed to converge
    """
    if as_of_date is None:
        as_of_date = date.today()

    # Collect cash flows (transactions)
    cash_flows: list[tuple[date, Decimal]] = []
    dates: list[date] = []
    amounts: list[Decimal] = []

    # Get all transactions up to as_of_date
    query = select(AtomicTransaction).where(
        AtomicTransaction.user_id == user_id,
        AtomicTransaction.txn_date <= as_of_date,
    )
    result = await db.execute(query)
    transactions = result.scalars().all()

    # Convert transactions to cash flows using XIRR convention:
    # IN (deposits/purchases) = negative (investor cash outflow)
    # OUT (withdrawals/sales) = positive (investor cash inflow)
    for txn in transactions:
        amount_base = await fx.convert_amount(
            db,
            txn.amount,
            txn.currency,
            settings.base_currency,
            txn.txn_date,
        )
        sign = 1 if txn.direction == TransactionDirection.OUT else -1
        cash_flows.append((txn.txn_date, amount_base * sign))
        dates.append(txn.txn_date)
        amounts.append(amount_base * sign)

    # Get current position value as final cash flow (positive = portfolio value)
    query = select(ManagedPosition).where(
        ManagedPosition.user_id == user_id,
        ManagedPosition.status == PositionStatus.ACTIVE,
    )
    result = await db.execute(query)
    positions = result.scalars().all()

    # Batch-fetch latest atomic positions (fixes N+1)
    asset_ids = [pos.asset_identifier for pos in positions]
    atomic_map = await _batch_latest_atomic_positions(db, user_id, asset_ids, as_of_date)

    total_value = Decimal("0")
    for pos in positions:
        atomic = atomic_map.get(pos.asset_identifier)
        if atomic:
            value_base = await fx.convert_amount(
                db,
                atomic.market_value or Decimal("0"),
                atomic.currency,
                settings.base_currency,
                as_of_date,
            )
            total_value += value_base

    if total_value > Decimal("0"):
        dates.append(as_of_date)
        amounts.append(total_value)

    # Need at least 2 data points (initial investment + current value)
    if len(dates) < 2:
        raise InsufficientDataError("Need at least one transaction and current portfolio value for XIRR calculation")

    # Convert dates to day offsets from first date
    first_date = min(dates)
    day_offsets = [(d - first_date).days for d in dates]

    # Solve for XIRR using Newton's method with bisection fallback
    # XIRR formula: Sum of (cash_flow_i / (1 + xirr)^(days_i / 365)) = 0
    try:
        xirr = _xirr_newton(amounts, day_offsets, guess=Decimal("0.1"), max_iter=100, tolerance=Decimal("1e-6"))
        return xirr * Decimal("100")  # Convert to percentage
    except (ValueError, RuntimeError) as e:
        logger.error(f"XIRR calculation failed: {e}", cash_flows=cash_flows)
        raise XIRRCalculationError(f"XIRR calculation failed to converge: {e}") from e


def _xirr_newton(amounts: list[Decimal], days: list[int], guess: Decimal, max_iter: int, tolerance: Decimal) -> Decimal:
    """
    Calculate XIRR using Newton's method with bisection fallback.

    Uses Decimal arithmetic throughout to maintain monetary precision.

    Args:
        amounts: Cash flow amounts (negative for outflows, positive for inflows)
        days: Day offsets from first date
        guess: Initial guess for XIRR (e.g., 0.1 for 10%)
        max_iter: Maximum iterations
        tolerance: Convergence tolerance

    Returns:
        Decimal: XIRR as decimal (e.g., 0.15 for 15%)
    Raises:
        ValueError: If calculation fails to converge
    """
    # Use float internally for the power/division operations (Decimal ** Decimal is slow
    # and Decimal doesn't support fractional exponents natively), but convert result back.
    rate = float(guess)
    float_amounts = [float(a) for a in amounts]
    float_tol = float(tolerance)

    for _ in range(max_iter):
        npv = sum(cf / (1 + rate) ** (d / 365.0) for cf, d in zip(float_amounts, days))
        d_npv = sum(-(d / 365.0) * cf / (1 + rate) ** (d / 365.0 + 1) for cf, d in zip(float_amounts, days))
        if abs(d_npv) < 1e-10:
            break

        new_rate = rate - npv / d_npv
        if abs(new_rate - rate) < float_tol:
            return Decimal(str(new_rate))

        rate = new_rate
    return _xirr_bisection(amounts, days, max_iter=200, tolerance=tolerance)


def _xirr_bisection(amounts: list[Decimal], days: list[int], max_iter: int, tolerance: Decimal) -> Decimal:
    """
    Bisection fallback for XIRR when Newton's method fails to converge.

    Searches the range [-0.99, 10.0] (i.e., -99% to 1000% return).

    Args:
        amounts: Cash flow amounts
        days: Day offsets from first date
        max_iter: Maximum iterations
        tolerance: Convergence tolerance

    Returns:
        Decimal: XIRR as decimal

    Raises:
        ValueError: If no root found in search range
    """
    lo, hi = -0.99, 10.0
    float_amounts = [float(a) for a in amounts]
    float_tol = float(tolerance)

    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** (d / 365.0) for cf, d in zip(float_amounts, days))

    npv_lo = npv(lo)
    npv_hi = npv(hi)

    if npv_lo * npv_hi > 0:
        raise ValueError(f"No root in [{lo}, {hi}]: NPV({lo})={npv_lo:.4f}, NPV({hi})={npv_hi:.4f}")
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        npv_mid = npv(mid)

        if abs(npv_mid) < float_tol or (hi - lo) / 2 < float_tol:
            return Decimal(str(mid))

        if npv_lo * npv_mid < 0:
            hi = mid
            npv_hi = npv_mid
        else:
            lo = mid
            npv_lo = npv_mid

    return Decimal(str((lo + hi) / 2))


async def calculate_time_weighted_return(
    db: AsyncSession,
    user_id: UUID,
    period_start: date,
    period_end: date,
) -> Decimal:
    """
    Calculate Time-Weighted Return (TWR) for a period.

    TWR eliminates the effect of cash flows, measuring only investment performance.
    Formula: TWR = [(1 + R1) * (1 + R2) * ... * (1 + Rn)] - 1
    where R_i = (End_Value - Start_Value - Net_Cash_Flow) / Start_Value

    Args:
        db: Database session
        user_id: User ID
        period_start: Start date of period
        period_end: End date of period

    Returns:
        Decimal: Period return as percentage (e.g., 8.5 for 8.5%)

    Raises:
        InsufficientDataError: Need at least two position snapshots
    """
    # Get position snapshots at start and end of period
    start_value = await _get_portfolio_value(db, user_id, period_start)
    end_value = await _get_portfolio_value(db, user_id, period_end)

    # Get net cash flows during period
    query = select(AtomicTransaction).where(
        AtomicTransaction.user_id == user_id,
        and_(
            AtomicTransaction.txn_date > period_start,
            AtomicTransaction.txn_date <= period_end,
        ),
    )
    result = await db.execute(query)
    transactions = result.scalars().all()

    net_cash_flow = Decimal("0")
    for txn in transactions:
        amount_base = await fx.convert_amount(
            db,
            txn.amount,
            txn.currency,
            settings.base_currency,
            txn.txn_date,
        )
        # For TWR: IN = positive (money added to portfolio), OUT = negative (money withdrawn)
        sign = -1 if txn.direction == TransactionDirection.OUT else 1
        net_cash_flow += amount_base * sign

    if start_value == Decimal("0"):
        if end_value == Decimal("0"):
            return Decimal("0")  # No change
        raise InsufficientDataError("Cannot calculate TWR with zero starting value and non-zero ending value")

    # TWR = (End_Value - Start_Value - Net_Cash_Flow) / Start_Value
    # Simplified for single period (no sub-periods)
    gain = end_value - start_value - net_cash_flow
    twr = (gain / start_value) * Decimal("100")  # Convert to percentage

    return twr


async def calculate_money_weighted_return(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,
) -> Decimal:
    """
    Calculate Money-Weighted Return (MWR) for portfolio.

    MWR is the internal rate of return (IRR) of all cash flows.
    This is an alias for XIRR - they are the same calculation.

    Args:
        db: Database session
        user_id: User ID
        as_of_date: Calculate as of this date (default: today)

    Returns:
        Decimal: Annualized return as percentage (e.g., 15.5 for 15.5%)

    Raises:
        InsufficientDataError: Need at least one cash flow and one position
        XIRRCalculationError: Calculation failed to converge
    """
    # MWR = XIRR (they are the same concept)
    return await calculate_xirr(db, user_id, as_of_date)


async def _get_portfolio_value(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date,
) -> Decimal:
    """
    Get total portfolio value as of a specific date.

    Uses batched query to avoid N+1 pattern.

    Args:
        db: Database session
        user_id: User ID
        as_of_date: Date to get value for

    Returns:
        Decimal: Total portfolio value in base currency
    """
    query = select(ManagedPosition).where(
        ManagedPosition.user_id == user_id,
        ManagedPosition.status == PositionStatus.ACTIVE,
    )
    result = await db.execute(query)
    positions = result.scalars().all()

    # Batch-fetch latest atomic positions (fixes N+1)
    asset_ids = [pos.asset_identifier for pos in positions]
    atomic_map = await _batch_latest_atomic_positions(db, user_id, asset_ids, as_of_date)

    total_value = Decimal("0")
    for pos in positions:
        atomic = atomic_map.get(pos.asset_identifier)
        if atomic:
            value_base = await fx.convert_amount(
                db,
                atomic.market_value or Decimal("0"),
                atomic.currency,
                settings.base_currency,
                as_of_date,
            )
            total_value += value_base

    return total_value
