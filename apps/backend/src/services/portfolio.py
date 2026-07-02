"""Portfolio management service - Holdings and P&L calculations."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit.money import Money, to_money
from src.audit.quantity import Quantity
from src.audit.ratio import Ratio
from src.audit.unit_price import UnitPrice
from src.config import settings
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.models.market_data import StockPrice
from src.models.portfolio import (
    DividendIncome,
    InvestmentTransaction,
    InvestmentTransactionType,
    MarketDataOverride,
    PriceSource,
)
from src.observability import get_logger
from src.schemas.portfolio import (
    HoldingResponse,
    PortfolioSummaryResponse,
    PriceUpdateRequest,
    PriceUpdateResponse,
    RealizedPnLResponse,
    UnrealizedPnLResponse,
)
from src.schemas.provenance import DataProvenance
from src.services import fx

logger = get_logger(__name__)

PORTFOLIO_QUANTITY_UNIT = "units"


def _derive_provenance(source_documents: object) -> DataProvenance | None:
    """Conservatively derive a holding's provenance from its snapshot's source
    documents (EPIC-022 #868/#888).

    Returns "imported" only when there is concrete document evidence (a
    ``source_documents`` entry carrying a ``doc_id``). Returns None otherwise:
    we never infer "manual", so manual data can never be mislabelled as imported
    and import-without-evidence is never overclaimed.
    """
    # source_documents is stored either as {"documents": [...]} (brokerage
    # import) or as a bare [...] list; tolerate both.
    docs = source_documents
    if isinstance(docs, dict):
        docs = docs.get("documents", [])
    if isinstance(docs, list) and any(isinstance(doc, dict) and doc.get("doc_id") for doc in docs):
        return "imported"
    return None


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


async def _convert_pnl(
    db: AsyncSession,
    *,
    value: Money,
    value_rate_date: date,
    cost: Money,
    cost_rate_date: date,
    target_currency: str,
    quantize: bool,
) -> tuple[Money, Money, Money, Ratio]:
    """Convert a holding's value + cost to ``target_currency`` and derive P&L.

    The shared valuation tail used across holdings / unrealized / realized /
    snapshot paths: convert each leg at its own FX rate-date (no-op when already
    in target), optionally quantize per-value, then ``pnl = value - cost`` and the
    ``pnl / cost`` ratio. Returns ``(converted_value, converted_cost, pnl, ratio)``.
    """
    converted_value = await fx.convert_money(db, value, target_currency, rate_date=value_rate_date, lazy_load=True)
    converted_cost = await fx.convert_money(db, cost, target_currency, rate_date=cost_rate_date, lazy_load=True)
    if quantize:
        converted_value = converted_value.quantize()
        converted_cost = converted_cost.quantize()
    pnl = converted_value - converted_cost
    ratio = Ratio.fraction_or_zero(pnl.amount, converted_cost.amount)
    return converted_value, converted_cost, pnl, ratio


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
        if as_of_date is not None:
            return await self._get_snapshot_holdings(
                db,
                user_id=user_id,
                as_of_date=as_of_date,
                include_disposed=include_disposed,
            )

        eval_date = await self._default_holdings_eval_date(db, user_id)

        # Get all managed positions for user.
        # Order deterministically (asset_identifier, then id tiebreaker) so that
        # downstream limit/offset pagination returns stable, consistent pages
        # across requests.
        positions_query = (
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .options(selectinload(ManagedPosition.account))
            .order_by(ManagedPosition.asset_identifier, ManagedPosition.id)
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

            # Market value as money-per-unit × quantity, converted to base currency.
            # convert_money is a no-op when already in base, so no if/else branch.
            position_quantity = position.quantity_qty.quantize()
            market_value = UnitPrice(latest_price, position.currency, PORTFOLIO_QUANTITY_UNIT) * position_quantity
            converted_value, converted_cost, unrealized_pnl, unrealized_pnl_ratio = await _convert_pnl(
                db,
                value=market_value,
                value_rate_date=eval_date,
                cost=position.cost_basis_money,
                cost_rate_date=position.acquisition_date,
                target_currency=settings.base_currency,
                quantize=True,
            )
            currency = converted_value.currency.code

            # Get asset classification from latest AtomicPosition (scoped by user_id)
            asset_type = None
            sector = None
            geography = None

            provenance = None
            latest_atomic = await self._get_latest_atomic(db, position.asset_identifier, user_id)
            if latest_atomic:
                asset_type = latest_atomic.asset_type
                sector = latest_atomic.sector
                geography = latest_atomic.geography
                provenance = _derive_provenance(latest_atomic.source_documents)

            holding = HoldingResponse(
                id=position.id,
                user_id=position.user_id,
                account_id=position.account_id,
                asset_identifier=position.asset_identifier,
                quantity=position.quantity,
                cost_basis=converted_cost.amount,
                market_value=converted_value.amount,
                unrealized_pnl=unrealized_pnl.amount,
                unrealized_pnl_percent=unrealized_pnl_ratio.to_percent(),
                currency=currency,
                # #1098: native (pre-conversion) cost basis so callers can
                # reconcile against /assets/positions' native values.
                native_cost_basis=position.cost_basis_money.amount,
                native_currency=position.cost_basis_money.currency.code,
                acquisition_date=position.acquisition_date,
                disposal_date=position.disposal_date,
                status=position.status,
                cost_basis_method=position.cost_basis_method,
                account_name=position.account.name if position.account else None,
                asset_type=asset_type,
                sector=sector,
                geography=geography,
                provenance=provenance,
            )
            holdings.append(holding)

        await db.flush()
        return holdings

    async def _get_snapshot_holdings(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        as_of_date: date,
        include_disposed: bool,
    ) -> Sequence[HoldingResponse]:
        """Return point-in-time holdings from immutable AtomicPosition snapshots."""
        latest_snapshot_subquery = (
            select(
                AtomicPosition.id,
                func.row_number()
                .over(
                    partition_by=[AtomicPosition.asset_identifier, AtomicPosition.broker],
                    order_by=[AtomicPosition.snapshot_date.desc(), AtomicPosition.created_at.desc()],
                )
                .label("rn"),
            )
            .where(AtomicPosition.user_id == user_id)
            .where(AtomicPosition.snapshot_date <= as_of_date)
            .subquery()
        )

        result = await db.execute(
            select(AtomicPosition)
            .join(latest_snapshot_subquery, AtomicPosition.id == latest_snapshot_subquery.c.id)
            .where(latest_snapshot_subquery.c.rn == 1)
            .order_by(AtomicPosition.asset_identifier)
        )
        snapshots = list(result.scalars().all())
        if not snapshots:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id} as of {as_of_date}")

        holdings: list[HoldingResponse] = []
        for snapshot in snapshots:
            snapshot_quantity = Quantity(snapshot.quantity, PORTFOLIO_QUANTITY_UNIT).quantize()
            status = PositionStatus.DISPOSED if snapshot_quantity.is_zero() else PositionStatus.ACTIVE
            if status == PositionStatus.DISPOSED and not include_disposed:
                continue

            position = await self._get_managed_position_for_snapshot(db, user_id=user_id, snapshot=snapshot)
            if position is None:
                logger.warning(
                    "Skipping atomic snapshot without reconciled managed position",
                    snapshot_id=str(snapshot.id),
                    asset_identifier=snapshot.asset_identifier,
                    as_of_date=as_of_date.isoformat(),
                )
                continue

            synced_price = await self._get_latest_synced_stock_price(db, snapshot.asset_identifier, as_of_date)
            if synced_price is not None and not snapshot_quantity.is_zero():
                market_money = (
                    UnitPrice(synced_price.price, synced_price.currency, PORTFOLIO_QUANTITY_UNIT) * snapshot_quantity
                )
                cost_money = position.cost_basis_money
                # managed-position cost is converted at its acquisition-date FX
                # boundary (consistent with get_holdings + the reporting SSOT).
                cost_rate_date = position.acquisition_date
            else:
                # snapshot proxy: cost == market, both at as_of_date so the
                # fallback unrealized P&L stays zero.
                market_money = Money(snapshot.market_value, snapshot.currency)
                cost_money = Money(snapshot.market_value, snapshot.currency)
                cost_rate_date = as_of_date

            # Market and cost may carry different source currencies (and rate-dates);
            # convert each to base (no-op when already base) and derive P&L.
            converted_market_value, converted_cost_basis, unrealized_pnl, unrealized_pnl_ratio = await _convert_pnl(
                db,
                value=market_money,
                value_rate_date=as_of_date,
                cost=cost_money,
                cost_rate_date=cost_rate_date,
                target_currency=settings.base_currency,
                quantize=True,
            )
            currency = converted_market_value.currency.code

            holdings.append(
                HoldingResponse(
                    id=position.id,
                    user_id=user_id,
                    account_id=position.account_id,
                    asset_identifier=snapshot.asset_identifier,
                    quantity=snapshot.quantity,
                    cost_basis=converted_cost_basis.amount,
                    market_value=converted_market_value.amount,
                    unrealized_pnl=unrealized_pnl.amount,
                    unrealized_pnl_percent=unrealized_pnl_ratio.to_percent(),
                    currency=currency,
                    # #1098: native (pre-conversion) cost basis + currency.
                    native_cost_basis=cost_money.amount,
                    native_currency=cost_money.currency.code,
                    acquisition_date=position.acquisition_date,
                    disposal_date=snapshot.snapshot_date if status == PositionStatus.DISPOSED else None,
                    status=status,
                    cost_basis_method=position.cost_basis_method,
                    account_name=position.account.name if position.account else None,
                    asset_type=snapshot.asset_type,
                    sector=snapshot.sector,
                    geography=snapshot.geography,
                    provenance=_derive_provenance(snapshot.source_documents),
                )
            )

        if not holdings:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id} as of {as_of_date}")

        await db.flush()
        return holdings

    async def _get_managed_position_for_snapshot(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        snapshot: AtomicPosition,
    ) -> ManagedPosition | None:
        """Find the reconciled managed position that corresponds to an atomic snapshot."""
        result = await db.execute(
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.asset_identifier == snapshot.asset_identifier)
            .options(selectinload(ManagedPosition.account))
        )
        positions = list(result.scalars().all())
        if not positions:
            return None

        broker = (snapshot.broker or "").strip().lower()
        if broker:
            for position in positions:
                account = position.account
                metadata_broker = str((position.position_metadata or {}).get("broker", "")).strip().lower()
                account_name = account.name.strip().lower() if account else ""
                if metadata_broker == broker or account_name == broker:
                    return position

        active_position = next((position for position in positions if position.status == PositionStatus.ACTIVE), None)
        return active_position or positions[0]

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
            position_quantity = position.quantity_qty.quantize()
            disposal_value = UnitPrice(disposal_price, position.currency, PORTFOLIO_QUANTITY_UNIT) * position_quantity

            # Disposal valued at disposal-date FX, cost at acquisition-date FX; per-position
            # values are not quantized here — only the response total is.
            converted_disposal, converted_cost, realized_pnl, realized_pnl_ratio = await _convert_pnl(
                db,
                value=disposal_value,
                value_rate_date=position.disposal_date,
                cost=position.cost_basis_money,
                cost_rate_date=position.acquisition_date,
                target_currency=settings.base_currency,
                quantize=False,
            )

            total_realized_pnl += realized_pnl.amount
            total_converted_cost += converted_cost.amount

            details.append(
                {
                    "asset_identifier": position.asset_identifier,
                    "quantity": position.quantity,
                    "disposal_date": position.disposal_date,
                    "disposal_price": disposal_price,
                    "cost_basis": converted_cost.amount,
                    "disposal_value": converted_disposal.amount,
                    "realized_pnl": realized_pnl.amount,
                    "realized_pnl_percent": realized_pnl_ratio.to_percent(),
                    # amounts above are converted to base, so label them with base
                    # (was position.currency — mislabelled converted amounts).
                    "currency": converted_cost.currency.code,
                    "cost_basis_method": position.cost_basis_method,
                }
            )

        # Calculate overall percent using converted costs (not raw costs)
        total_realized_pnl_ratio = Ratio.fraction_or_zero(total_realized_pnl, total_converted_cost)

        await db.flush()
        return RealizedPnLResponse(
            period_start=period_start,
            period_end=period_end,
            total_realized_pnl=to_money(total_realized_pnl),
            total_realized_pnl_percent=total_realized_pnl_ratio.to_percent(),
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
            position_quantity = position.quantity_qty.quantize()
            market_value = UnitPrice(latest_price, position.currency, PORTFOLIO_QUANTITY_UNIT) * position_quantity

            # Per-position values are not quantized here — only the response total is.
            converted_market, converted_cost, unrealized_pnl, unrealized_pnl_ratio = await _convert_pnl(
                db,
                value=market_value,
                value_rate_date=eval_date,
                cost=position.cost_basis_money,
                cost_rate_date=position.acquisition_date,
                target_currency=settings.base_currency,
                quantize=False,
            )
            currency = converted_market.currency.code

            total_market_value += converted_market.amount
            total_cost_basis += converted_cost.amount
            total_unrealized_pnl += unrealized_pnl.amount
            details.append(
                {
                    "asset_identifier": position.asset_identifier,
                    "quantity": position.quantity,
                    "current_price": latest_price,
                    "market_value": converted_market.amount,
                    "cost_basis": converted_cost.amount,
                    "unrealized_pnl": unrealized_pnl.amount,
                    "unrealized_pnl_percent": unrealized_pnl_ratio.to_percent(),
                    "currency": currency,
                }
            )

        # Calculate overall percent
        total_unrealized_pnl_ratio = Ratio.fraction_or_zero(total_unrealized_pnl, total_cost_basis)

        await db.flush()
        return UnrealizedPnLResponse(
            as_of_date=eval_date,
            total_unrealized_pnl=to_money(total_unrealized_pnl),
            total_unrealized_pnl_percent=total_unrealized_pnl_ratio.to_percent(),
            total_market_value=to_money(total_market_value),
            total_cost_basis=to_money(total_cost_basis),
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
        net_pnl_ratio = Ratio.fraction_or_zero(net_pnl, total_cost_basis)

        return PortfolioSummaryResponse(
            total_market_value=to_money(total_market_value),
            total_cost_basis=to_money(total_cost_basis),
            total_unrealized_pnl=to_money(total_unrealized_pnl),
            total_unrealized_pnl_percent=net_pnl_ratio.to_percent(),
            total_realized_pnl=Decimal("0"),  # Phase 1 only
            total_realized_pnl_percent=Ratio.zero().to_percent(),
            net_pnl=to_money(net_pnl),
            net_pnl_percent=net_pnl_ratio.to_percent(),
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

        synced_price = await self._get_latest_synced_stock_price(db, position.asset_identifier, eval_date)
        if synced_price is not None:
            if synced_price.currency == position.currency:
                return synced_price.price
            return await fx.convert_amount(
                db,
                amount=synced_price.price,
                currency=synced_price.currency,
                target_currency=position.currency,
                rate_date=eval_date,
                lazy_load=True,
            )

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
            snapshot_quantity = Quantity(snapshot.quantity, PORTFOLIO_QUANTITY_UNIT).quantize()
            if not snapshot_quantity.is_zero():
                return snapshot.market_value / snapshot_quantity.value
            return snapshot.market_value

        # No price data available
        raise AssetNotFoundError(f"No price data available for {position.asset_identifier} on {eval_date}")

    async def _get_latest_synced_stock_price(
        self,
        db: AsyncSession,
        asset_identifier: str,
        eval_date: date,
    ) -> StockPrice | None:
        """Return the latest synced daily stock price on or before eval_date."""
        return await db.scalar(
            select(StockPrice)
            .where(StockPrice.symbol == asset_identifier.strip().upper())
            .where(StockPrice.price_date <= eval_date)
            .order_by(
                StockPrice.price_date.desc(),
                StockPrice.created_at.desc(),
                StockPrice.source.asc(),
                StockPrice.currency.asc(),
                StockPrice.id.asc(),
            )
            .limit(1)
        )

    async def _default_holdings_eval_date(self, db: AsyncSession, user_id: UUID) -> date:
        """Use today unless the latest imported portfolio snapshot is newer."""
        latest_snapshot_date = await db.scalar(
            select(func.max(AtomicPosition.snapshot_date)).where(AtomicPosition.user_id == user_id)
        )
        today = date.today()
        if latest_snapshot_date and latest_snapshot_date > today:
            return latest_snapshot_date
        return today

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

    async def get_realized_pnl_by_asset(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        start_date: date,
        end_date: date,
        target_currency: str,
    ) -> tuple[dict[str, Decimal], set[str]]:
        """Per-asset realized P&L from SELL transactions in ``[start_date, end_date]``.

        Each transaction's realized P&L is converted to ``target_currency`` at the
        transaction date. Returns ``(by_asset, source_refs)`` where ``source_refs``
        carries journal-entry / transaction-source links for traceability. Raises
        ``fx.FxRateError`` when a required rate is unavailable.
        """
        result = await db.execute(
            select(InvestmentTransaction)
            .where(InvestmentTransaction.user_id == user_id)
            .where(InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL)
            .where(InvestmentTransaction.transaction_date >= start_date)
            .where(InvestmentTransaction.transaction_date <= end_date)
        )
        by_asset: dict[str, Decimal] = {}
        source_refs: set[str] = set()
        for txn in result.scalars().all():
            amount = await fx.convert_amount(
                db,
                txn.realized_pnl or Decimal("0.00"),
                txn.currency,
                target_currency,
                txn.transaction_date,
                lazy_load=True,
            )
            by_asset[txn.asset_identifier] = by_asset.get(txn.asset_identifier, Decimal("0.00")) + amount
            if txn.journal_entry_id:
                source_refs.add(f"journal_entry:{txn.journal_entry_id}")
            if txn.source_id:
                source_refs.add(f"investment_transaction_source:{txn.source_id}")
        return by_asset, source_refs

    async def get_dividend_income_by_asset(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        start_date: date,
        end_date: date,
        target_currency: str,
    ) -> dict[str, Decimal]:
        """Per-asset dividend income in ``[start_date, end_date]``.

        Each dividend is converted to ``target_currency`` at the payment date and
        grouped by the owning position's asset identifier. Raises ``fx.FxRateError``
        when a required rate is unavailable.
        """
        result = await db.execute(
            select(DividendIncome, ManagedPosition)
            .join(ManagedPosition, DividendIncome.position_id == ManagedPosition.id)
            .where(DividendIncome.user_id == user_id)
            .where(ManagedPosition.user_id == user_id)
            .where(DividendIncome.payment_date >= start_date)
            .where(DividendIncome.payment_date <= end_date)
        )
        by_asset: dict[str, Decimal] = {}
        for dividend, position in result.all():
            amount = await fx.convert_amount(
                db,
                dividend.amount,
                dividend.currency,
                target_currency,
                dividend.payment_date,
                lazy_load=True,
            )
            by_asset[position.asset_identifier] = by_asset.get(position.asset_identifier, Decimal("0.00")) + amount
        return by_asset


# Shared singleton instance reused by the portfolio router and the
# performance-report service so monkeypatching one reference affects both.
portfolio_service = PortfolioService()
