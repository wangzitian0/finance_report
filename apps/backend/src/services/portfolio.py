"""Portfolio management service - Holdings and P&L calculations."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.logger import get_logger
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.models.portfolio import MarketDataOverride, PriceSource
from src.schemas.portfolio import (
    HoldingResponse,
    PortfolioSummaryResponse,
    PriceUpdateRequest,
    PriceUpdateResponse,
    RealizedPnLResponse,
    UnrealizedPnLResponse,
)
from src.services import fx

logger = get_logger(__name__)


class PortfolioError(Exception):
    """Base exception for portfolio service errors."""

    pass


class PortfolioNotFoundError(PortfolioError):
    """Raised when portfolio positions are not found for a user."""

    pass


class InvalidDateRangeError(PortfolioError):
    """Raised when date range is invalid."""

    pass


class AssetNotFoundError(PortfolioError):
    """Raised when asset is not found."""

    pass


class PortfolioService:
    """Service for managing portfolio holdings and P&L calculations."""

    async def get_holdings(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
        include_disposed: bool = False,
    ) -> Sequence[HoldingResponse]:
        """
        Get portfolio holdings summary.

        Returns holdings for active positions. Includes denormalized fields from
        AtomicPosition (asset_type, sector, geography) when available.

        Args:
            db: Database session
            user_id: User UUID
            as_of_date: Date to evaluate positions as of (default: today)
            include_disposed: Include disposed positions in results

        Returns:
            List of holdings with market values and P&L calculations

        Raises:
            PortfolioNotFoundError: If user has no positions
        """
        # Default to today if not specified
        eval_date = as_of_date or date.today()

        # Get all managed positions for user
        positions_query = (
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .options(selectinload(ManagedPosition.account))
        )

        if not include_disposed:
            positions_query = positions_query.where(ManagedPosition.status == PositionStatus.ACTIVE)

        result = await db.execute(positions_query)
        positions = result.scalars().all()

        if not positions:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id}")

        holdings: list[HoldingResponse] = []

        for position in positions:
            # Get latest market price from AtomicPosition (per-unit price)
            latest_price = await self._get_latest_price(db, position, eval_date, user_id)

            # Calculate market value
            market_value = position.quantity * latest_price

            # Convert to base currency if needed
            if position.currency != settings.base_currency:
                converted_value = await fx.convert_amount(
                    db,
                    amount=market_value,
                    currency=position.currency,
                    target_currency=settings.base_currency,
                    rate_date=eval_date,
                )
                converted_cost = await fx.convert_amount(
                    db,
                    amount=position.cost_basis,
                    currency=position.currency,
                    target_currency=settings.base_currency,
                    rate_date=position.acquisition_date,
                )
                currency = settings.base_currency
            else:
                converted_value = market_value
                converted_cost = position.cost_basis
                currency = position.currency

            # Calculate P&L (unrealized: market_value - cost_basis)
            unrealized_pnl = converted_value - converted_cost
            if converted_cost != Decimal("0"):
                unrealized_pnl_percent = (unrealized_pnl / converted_cost) * Decimal("100")
            else:
                unrealized_pnl_percent = Decimal("0")

            # Get asset classification from latest AtomicPosition (scoped by user_id)
            asset_type = None
            sector = None
            geography = None

            latest_atomic = await self._get_latest_atomic(db, position.asset_identifier, user_id)
            if latest_atomic:
                asset_type = latest_atomic.asset_type
                sector = latest_atomic.sector
                geography = latest_atomic.geography

            holding = HoldingResponse(
                id=position.id,
                user_id=position.user_id,
                account_id=position.account_id,
                asset_identifier=position.asset_identifier,
                quantity=position.quantity,
                cost_basis=converted_cost,
                market_value=converted_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_percent=unrealized_pnl_percent.quantize(Decimal("0.01")),
                currency=currency,
                acquisition_date=position.acquisition_date,
                disposal_date=position.disposal_date,
                status=position.status,
                cost_basis_method=position.cost_basis_method,
                account_name=position.account.name if position.account else None,
                asset_type=asset_type,
                sector=sector,
                geography=geography,
            )
            holdings.append(holding)

        await db.flush()
        return holdings

    async def calculate_realized_pnl(
        self,
        db: AsyncSession,
        user_id: UUID,
        period_start: date,
        period_end: date,
    ) -> RealizedPnLResponse:
        """
        Calculate realized P&L for a user within a date range.

        Uses cost basis method (FIFO/LIFO/AvgCost) stored in position.

        Args:
            db: Database session
            user_id: User UUID
            period_start: Start date of the period (inclusive)
            period_end: End date of the period (inclusive)

        Returns:
            Realized P&L with position breakdown

        Raises:
            InvalidDateRangeError: If period_start > period_end
            PortfolioNotFoundError: If user has no disposed positions
        """
        if period_start > period_end:
            raise InvalidDateRangeError(f"period_start ({period_start}) cannot be after period_end ({period_end})")

        # Get disposed positions
        disposed_positions_query = (
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.status == PositionStatus.DISPOSED)
            .where(ManagedPosition.disposal_date.isnot(None))
            .where(ManagedPosition.disposal_date.between(period_start, period_end))
            .options(selectinload(ManagedPosition.account))
        )

        result = await db.execute(disposed_positions_query)
        disposed_positions = result.scalars().all()

        if not disposed_positions:
            return RealizedPnLResponse(
                period_start=period_start,
                period_end=period_end,
                total_realized_pnl=Decimal("0"),
                total_realized_pnl_percent=Decimal("0"),
                positions_count=0,
                details=[],
            )

        total_realized_pnl = Decimal("0")
        total_converted_cost = Decimal("0")
        details: list[dict] = []

        for position in disposed_positions:
            # Get disposal price from latest AtomicPosition (per-unit price)
            # disposal_date is guaranteed non-None by the isnot(None) filter above
            assert position.disposal_date is not None
            disposal_price = await self._get_latest_price(db, position, position.disposal_date, user_id)
            disposal_value = position.quantity * disposal_price

            # Convert to base currency if needed
            if position.currency != settings.base_currency:
                converted_disposal = await fx.convert_amount(
                    db,
                    amount=disposal_value,
                    currency=position.currency,
                    target_currency=settings.base_currency,
                    rate_date=position.disposal_date,
                )
                converted_cost = await fx.convert_amount(
                    db,
                    amount=position.cost_basis,
                    currency=position.currency,
                    target_currency=settings.base_currency,
                    rate_date=position.acquisition_date,
                )
            else:
                converted_disposal = disposal_value
                converted_cost = position.cost_basis

            # Calculate P&L based on cost basis method
            realized_pnl = converted_disposal - converted_cost

            if converted_cost != Decimal("0"):
                realized_pnl_percent = (realized_pnl / converted_cost) * Decimal("100")
            else:
                realized_pnl_percent = Decimal("0")

            total_realized_pnl += realized_pnl
            total_converted_cost += converted_cost

            details.append(
                {
                    "asset_identifier": position.asset_identifier,
                    "quantity": position.quantity,
                    "disposal_date": position.disposal_date,
                    "disposal_price": disposal_price,
                    "cost_basis": converted_cost,
                    "disposal_value": converted_disposal,
                    "realized_pnl": realized_pnl,
                    "realized_pnl_percent": realized_pnl_percent.quantize(Decimal("0.01")),
                    "currency": position.currency,
                    "cost_basis_method": position.cost_basis_method,
                }
            )

        # Calculate overall percent using converted costs (not raw costs)
        if total_converted_cost != Decimal("0"):
            total_realized_pnl_percent = (total_realized_pnl / total_converted_cost) * Decimal("100")
        else:
            total_realized_pnl_percent = Decimal("0")

        await db.flush()
        return RealizedPnLResponse(
            period_start=period_start,
            period_end=period_end,
            total_realized_pnl=total_realized_pnl.quantize(Decimal("0.01")),
            total_realized_pnl_percent=total_realized_pnl_percent.quantize(Decimal("0.01")),
            positions_count=len(disposed_positions),
            details=details,
        )

    async def calculate_unrealized_pnl(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
    ) -> UnrealizedPnLResponse:
        """
        Calculate unrealized P&L for user's portfolio as of a specific date.

        Unrealized P&L = market_value - cost_basis (at as_of_date)

        Args:
            db: Database session
            user_id: User UUID
            as_of_date: Date to evaluate positions (default: today)

        Returns:
            Unrealized P&L summary with position breakdown

        Raises:
            PortfolioNotFoundError: If user has no positions
        """
        eval_date = as_of_date or date.today()

        # Get all active positions for user
        positions_query = (
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.status == PositionStatus.ACTIVE)
        )

        result = await db.execute(positions_query)
        positions = result.scalars().all()

        if not positions:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id}")

        total_market_value = Decimal("0")
        total_cost_basis = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        details: list[dict] = []

        for position in positions:
            # Get latest market price from AtomicPosition (per-unit price)
            latest_price = await self._get_latest_price(db, position, eval_date, user_id)

            # Calculate market value
            market_value = position.quantity * latest_price

            # Convert to base currency if needed
            if position.currency != settings.base_currency:
                converted_market = await fx.convert_amount(
                    db,
                    amount=market_value,
                    currency=position.currency,
                    target_currency=settings.base_currency,
                    rate_date=eval_date,
                )
                converted_cost = await fx.convert_amount(
                    db,
                    amount=position.cost_basis,
                    currency=position.currency,
                    target_currency=settings.base_currency,
                    rate_date=position.acquisition_date,
                )
                currency = settings.base_currency
            else:
                converted_market = market_value
                converted_cost = position.cost_basis
                currency = position.currency

            # Calculate unrealized P&L
            unrealized_pnl = converted_market - converted_cost
            total_market_value += converted_market
            total_cost_basis += converted_cost
            total_unrealized_pnl += unrealized_pnl

            details.append(
                {
                    "asset_identifier": position.asset_identifier,
                    "quantity": position.quantity,
                    "current_price": latest_price,
                    "market_value": converted_market,
                    "cost_basis": converted_cost,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_percent": (
                        (unrealized_pnl / converted_cost * Decimal("100"))
                        if converted_cost != Decimal("0")
                        else Decimal("0")
                    ).quantize(Decimal("0.01")),
                    "currency": currency,
                }
            )

        # Calculate overall percent
        if total_cost_basis != Decimal("0"):
            total_unrealized_pnl_percent = (total_unrealized_pnl / total_cost_basis) * Decimal("100")
        else:
            total_unrealized_pnl_percent = Decimal("0")

        await db.flush()
        return UnrealizedPnLResponse(
            as_of_date=eval_date,
            total_unrealized_pnl=total_unrealized_pnl.quantize(Decimal("0.01")),
            total_unrealized_pnl_percent=total_unrealized_pnl_percent.quantize(Decimal("0.01")),
            total_market_value=total_market_value.quantize(Decimal("0.01")),
            total_cost_basis=total_cost_basis.quantize(Decimal("0.01")),
            holdings_count=len(positions),
            details=details,
        )

    async def update_market_prices(
        self,
        db: AsyncSession,
        user_id: UUID,
        updates: list[PriceUpdateRequest],
    ) -> list[PriceUpdateResponse]:
        """
        Update market prices for holdings (manual overrides).

        Inserts new records into market_data_override table, which takes
        precedence over API-sourced prices.

        Args:
            db: Database session
            user_id: User UUID
            updates: List of price update requests

        Returns:
            List of price update responses with success status
        """
        responses: list[PriceUpdateResponse] = []

        for update in updates:
            # Validate asset exists and belongs to user
            asset_query = (
                select(ManagedPosition)
                .where(ManagedPosition.user_id == user_id)
                .where(ManagedPosition.asset_identifier == update.asset_identifier)
            )
            result = await db.execute(asset_query)
            position = result.scalar_one_or_none()

            if not position:
                responses.append(
                    PriceUpdateResponse(
                        success=False,
                        message=f"Asset {update.asset_identifier} not found for user",
                        asset_identifier=update.asset_identifier,
                        price_date=update.price_date,
                        price=update.price,
                        currency=update.currency,
                        source="",
                        created_at=None,
                    )
                )
                continue

            # Create market data override (scoped to user)
            override = MarketDataOverride(
                user_id=user_id,
                asset_identifier=update.asset_identifier,
                price_date=update.price_date,
                price=update.price,
                currency=update.currency,
                source=PriceSource.MANUAL,
            )
            db.add(override)
            await db.flush()  # Flush to populate created_at

            responses.append(
                PriceUpdateResponse(
                    success=True,
                    message="Price updated successfully",
                    asset_identifier=update.asset_identifier,
                    price_date=update.price_date,
                    price=update.price,
                    currency=update.currency,
                    source="manual",
                    created_at=override.created_at,
                )
            )

        await db.flush()
        return responses

    async def get_portfolio_summary(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
    ) -> PortfolioSummaryResponse:
        """
        Get overall portfolio summary including total market value, P&L, etc.

        Args:
            db: Database session
            user_id: User UUID
            as_of_date: Date to evaluate positions (default: today)

        Returns:
            Comprehensive portfolio summary
        """
        holdings = await self.get_holdings(db, user_id, as_of_date, include_disposed=True)

        total_market_value = Decimal("0")
        total_cost_basis = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        active_positions_count = 0
        disposed_positions_count = 0

        for holding in holdings:
            total_market_value += holding.market_value
            total_cost_basis += holding.cost_basis
            total_unrealized_pnl += holding.unrealized_pnl

            if holding.status == PositionStatus.ACTIVE:
                active_positions_count += 1
            else:
                disposed_positions_count += 1

        # Calculate net P&L and percentages
        net_pnl = total_unrealized_pnl
        if total_cost_basis != Decimal("0"):
            net_pnl_percent = (net_pnl / total_cost_basis) * Decimal("100")
        else:
            net_pnl_percent = Decimal("0")

        return PortfolioSummaryResponse(
            total_market_value=total_market_value.quantize(Decimal("0.01")),
            total_cost_basis=total_cost_basis.quantize(Decimal("0.01")),
            total_unrealized_pnl=total_unrealized_pnl.quantize(Decimal("0.01")),
            total_unrealized_pnl_percent=net_pnl_percent.quantize(Decimal("0.01")),
            total_realized_pnl=Decimal("0"),  # Phase 1 only
            total_realized_pnl_percent=Decimal("0"),
            net_pnl=net_pnl.quantize(Decimal("0.01")),
            net_pnl_percent=net_pnl_percent.quantize(Decimal("0.01")),
            holdings_count=len(holdings),
            active_positions_count=active_positions_count,
            disposed_positions_count=disposed_positions_count,
            currency=holdings[0].currency if holdings else settings.base_currency,
        )

    async def _get_latest_price(
        self,
        db: AsyncSession,
        position: ManagedPosition,
        eval_date: date,
        user_id: UUID,
    ) -> Decimal:
        """
        Get latest per-unit market price for a position from override or AtomicPosition.

        Priority: MarketDataOverride > AtomicPosition snapshot on eval_date > earliest available.

        Args:
            db: Database session
            position: Managed position
            eval_date: Date to evaluate price
            user_id: User UUID for security scoping

        Returns:
            Latest per-unit price in position's currency

        Raises:
            AssetNotFoundError: If no price data available
        """
        # Check for manual override first (scoped by user_id)
        override_query = (
            select(MarketDataOverride)
            .where(MarketDataOverride.user_id == user_id)
            .where(MarketDataOverride.asset_identifier == position.asset_identifier)
            .where(MarketDataOverride.price_date == eval_date)
            .where(MarketDataOverride.source == PriceSource.MANUAL)
        )
        override_result = await db.execute(override_query)
        override = override_result.scalar_one_or_none()

        if override:
            return override.price

        # Get latest snapshot from AtomicPosition (scoped by user_id)
        snapshot_query = (
            select(AtomicPosition)
            .where(AtomicPosition.user_id == user_id)
            .where(AtomicPosition.asset_identifier == position.asset_identifier)
            .where(AtomicPosition.snapshot_date <= eval_date)
            .order_by(AtomicPosition.snapshot_date.desc())
            .limit(1)
        )
        snapshot_result = await db.execute(snapshot_query)
        snapshot = snapshot_result.scalar_one_or_none()

        if snapshot:
            # Return per-unit price (market_value is total position value)
            if snapshot.quantity != Decimal("0"):
                return snapshot.market_value / snapshot.quantity
            return snapshot.market_value

        # No price data available
        raise AssetNotFoundError(f"No price data available for {position.asset_identifier} on {eval_date}")

    async def _get_latest_atomic(
        self,
        db: AsyncSession,
        asset_identifier: str,
        user_id: UUID,
    ) -> AtomicPosition | None:
        """
        Get the latest AtomicPosition for an asset identifier.

        Used to fetch asset classification fields (asset_type, sector, geography).

        Args:
            db: Database session
            asset_identifier: Asset ticker or identifier
            user_id: User UUID for security scoping

        Returns:
            Latest AtomicPosition or None if not found
        """
        query = (
            select(AtomicPosition)
            .where(AtomicPosition.user_id == user_id)
            .where(AtomicPosition.asset_identifier == asset_identifier)
            .order_by(AtomicPosition.snapshot_date.desc())
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()
