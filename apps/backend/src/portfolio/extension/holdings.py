"""Portfolio management service - Holdings and P&L calculations."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency, Money, to_money
from src.audit.quantity import Quantity, Unit
from src.audit.ratio import Ratio
from src.audit.unit_price import UnitPrice
from src.config_app import get_effective_base_currency
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.layer3 import ManagedPosition, PositionStatus
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalLine, active_journal_entry_filter
from src.observability import get_logger
from src.portfolio.base.errors import (
    AssetNotFoundError,
    InvalidDateRangeError,
    PortfolioNotFoundError,
)
from src.portfolio.orm.portfolio import DividendIncome, InvestmentTransaction, InvestmentTransactionType
from src.pricing import MarketDataOverride, PriceSource, StockPrice, convert_amount, convert_money
from src.schemas.portfolio import (
    HoldingResponse,
    PortfolioSummaryDashboardResponse,
    PortfolioSummaryResponse,
    PriceUpdateRequest,
    PriceUpdateResponse,
    RealizedPnLResponse,
    UnrealizedPnLResponse,
)
from src.schemas.provenance import DataProvenance

logger = get_logger(__name__)

PORTFOLIO_QUANTITY_UNIT = Unit("units")


async def _account_names_by_id(
    db: AsyncSession,
    user_id: UUID,
    account_ids: set[UUID],
) -> dict[UUID, str]:
    """Resolve account display names for a set of ManagedPosition.account_ids (#1675 D4)."""
    if not account_ids:
        return {}
    rows = (await db.execute(select(Account.id, Account.name).where(Account.user_id == user_id, Account.id.in_(account_ids)))).all()
    return {aid: name for aid, name in rows}


def _derive_provenance(source_documents: object) -> DataProvenance | None:
    """Return 'imported' only when concrete doc_id evidence exists (#868/#888)."""
    docs = source_documents.get("documents", []) if isinstance(source_documents, dict) else source_documents
    if isinstance(docs, list) and any(isinstance(doc, dict) and doc.get("doc_id") for doc in docs):
        return "imported"
    return None


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
    """Convert a holding's value and cost to target_currency and derive P&L + ratio."""
    converted_value = await convert_money(db, value, target_currency, rate_date=value_rate_date, lazy_load=True)
    converted_cost = await convert_money(db, cost, target_currency, rate_date=cost_rate_date, lazy_load=True)
    if quantize:
        converted_value = converted_value.quantize()
        converted_cost = converted_cost.quantize()
    pnl = converted_value - converted_cost
    return converted_value, converted_cost, pnl, Ratio.fraction_or_zero(pnl.amount, converted_cost.amount)


class PortfolioService:
    """Service for managing portfolio holdings and P&L calculations."""

    async def _value_managed_position(
        self,
        db: AsyncSession,
        position: ManagedPosition,
        eval_date: date,
        user_id: UUID,
        target_currency: str,
        *,
        quantize: bool,
    ) -> tuple[Decimal, Money, Money, Money, Ratio]:
        latest_price = await self._get_latest_price(db, position, eval_date, user_id)
        position_quantity = position.quantity_qty.quantize()
        market_value = UnitPrice(latest_price, Currency(position.currency), PORTFOLIO_QUANTITY_UNIT) * position_quantity
        converted_value, converted_cost, pnl, pnl_ratio = await _convert_pnl(
            db,
            value=market_value,
            value_rate_date=eval_date,
            cost=position.cost_basis_money,
            cost_rate_date=position.acquisition_date,
            target_currency=target_currency,
            quantize=quantize,
        )
        return latest_price, converted_value, converted_cost, pnl, pnl_ratio

    async def get_holdings(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
        include_disposed: bool = False,
        warnings: list[dict[str, str]] | None = None,
    ) -> Sequence[HoldingResponse]:
        """Return portfolio holdings summary with market values and unrealized P&L."""
        if as_of_date is not None:
            return await self._get_snapshot_holdings(
                db, user_id=user_id, as_of_date=as_of_date, include_disposed=include_disposed, warnings=warnings
            )

        eval_date = await self._default_holdings_eval_date(db, user_id)
        positions_query = (
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .order_by(ManagedPosition.asset_identifier, ManagedPosition.id)
        )
        if not include_disposed:
            positions_query = positions_query.where(ManagedPosition.status == PositionStatus.ACTIVE)

        positions = (await db.scalars(positions_query)).all()
        if not positions:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id}")

        account_names = await _account_names_by_id(db, user_id, {p.account_id for p in positions})
        base_currency = await get_effective_base_currency(db, user_id=user_id)
        holdings: list[HoldingResponse] = []

        for position in positions:
            _, converted_value, converted_cost, unrealized_pnl, unrealized_pnl_ratio = await self._value_managed_position(
                db, position, eval_date, user_id, base_currency, quantize=True
            )
            latest_atomic = await self._get_latest_atomic(db, position.asset_identifier, user_id)
            holdings.append(
                HoldingResponse(
                    id=position.id,
                    user_id=position.user_id,
                    account_id=position.account_id,
                    asset_identifier=position.asset_identifier,
                    quantity=position.quantity,
                    cost_basis=converted_cost.amount,
                    market_value=converted_value.amount,
                    unrealized_pnl=unrealized_pnl.amount,
                    unrealized_pnl_percent=unrealized_pnl_ratio.to_percent(),
                    currency=converted_value.currency.code,
                    native_cost_basis=position.cost_basis_money.amount,
                    native_currency=position.cost_basis_money.currency.code,
                    acquisition_date=position.acquisition_date,
                    disposal_date=position.disposal_date,
                    status=position.status,
                    cost_basis_method=position.cost_basis_method,
                    account_name=account_names.get(position.account_id),
                    asset_type=latest_atomic.asset_type if latest_atomic else None,
                    sector=latest_atomic.sector if latest_atomic else None,
                    geography=latest_atomic.geography if latest_atomic else None,
                    provenance=_derive_provenance(latest_atomic.source_documents) if latest_atomic else None,
                )
            )

        await db.flush()
        return holdings

    async def _get_snapshot_holdings(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        as_of_date: date,
        include_disposed: bool,
        warnings: list[dict[str, str]] | None = None,
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
            .where(AtomicPosition.user_id == user_id, AtomicPosition.snapshot_date <= as_of_date)
            .subquery()
        )
        snapshots = list(
            (
                await db.scalars(
                    select(AtomicPosition)
                    .join(latest_snapshot_subquery, AtomicPosition.id == latest_snapshot_subquery.c.id)
                    .where(latest_snapshot_subquery.c.rn == 1)
                    .order_by(AtomicPosition.asset_identifier)
                )
            ).all()
        )
        if not snapshots:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id} as of {as_of_date}")

        holdings: list[HoldingResponse] = []
        account_names: dict[UUID, str] = {}
        base_currency = await get_effective_base_currency(db, user_id=user_id)
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
                if warnings is not None:
                    warnings.append(
                        {
                            "type": "unreconciled_snapshot_skipped",
                            "asset_identifier": snapshot.asset_identifier,
                            "as_of_date": as_of_date.isoformat(),
                            "message": (
                                f"Snapshot for {snapshot.asset_identifier} has no reconciled "
                                f"managed position and is excluded from holdings as of "
                                f"{as_of_date.isoformat()}."
                            ),
                        }
                    )
                continue

            if position.account_id not in account_names:
                account_names.update(await _account_names_by_id(db, user_id, {position.account_id}))

            synced_price = await self._get_latest_synced_stock_price(db, snapshot.asset_identifier, as_of_date)
            if synced_price is not None and not snapshot_quantity.is_zero():
                market_money = (
                    UnitPrice(synced_price.price, Currency(synced_price.currency), PORTFOLIO_QUANTITY_UNIT)
                    * snapshot_quantity
                )
                cost_money, cost_rate_date = position.cost_basis_money, position.acquisition_date
            else:
                market_money = cost_money = Money(snapshot.market_value, Currency(snapshot.currency))
                cost_rate_date = as_of_date

            converted_market_value, converted_cost_basis, unrealized_pnl, unrealized_pnl_ratio = await _convert_pnl(
                db,
                value=market_money,
                value_rate_date=as_of_date,
                cost=cost_money,
                cost_rate_date=cost_rate_date,
                target_currency=base_currency,
                quantize=True,
            )
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
                    currency=converted_market_value.currency.code,
                    native_cost_basis=cost_money.amount,
                    native_currency=cost_money.currency.code,
                    acquisition_date=position.acquisition_date,
                    disposal_date=snapshot.snapshot_date if status == PositionStatus.DISPOSED else None,
                    status=status,
                    cost_basis_method=position.cost_basis_method,
                    account_name=account_names.get(position.account_id),
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
        """Find the reconciled managed position corresponding to an atomic snapshot."""
        positions = list(
            (
                await db.scalars(
                    select(ManagedPosition).where(
                        ManagedPosition.user_id == user_id,
                        ManagedPosition.asset_identifier == snapshot.asset_identifier,
                    )
                )
            ).all()
        )
        if not positions:
            return None

        broker = (snapshot.broker or "").strip().lower()
        if broker:
            account_names = await _account_names_by_id(db, user_id, {p.account_id for p in positions})
            for position in positions:
                metadata_broker = str((position.position_metadata or {}).get("broker", "")).strip().lower()
                account_name = (account_names.get(position.account_id) or "").strip().lower()
                if metadata_broker == broker or account_name == broker:
                    return position

        return next((p for p in positions if p.status == PositionStatus.ACTIVE), positions[0])

    async def calculate_realized_pnl(
        self,
        db: AsyncSession,
        user_id: UUID,
        period_start: date,
        period_end: date,
    ) -> RealizedPnLResponse:
        """Calculate realized P&L for disposed positions within [period_start, period_end]."""
        if period_start > period_end:
            raise InvalidDateRangeError(f"period_start ({period_start}) cannot be after period_end ({period_end})")

        disposed_positions = (
            await db.scalars(
                select(ManagedPosition).where(
                    ManagedPosition.user_id == user_id,
                    ManagedPosition.status == PositionStatus.DISPOSED,
                    ManagedPosition.disposal_date.isnot(None),
                    ManagedPosition.disposal_date.between(period_start, period_end),
                )
            )
        ).all()
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
        base_currency = await get_effective_base_currency(db, user_id=user_id)

        for position in disposed_positions:
            assert position.disposal_date is not None
            disposal_price, converted_disposal, converted_cost, realized_pnl, realized_pnl_ratio = (
                await self._value_managed_position(
                    db, position, position.disposal_date, user_id, base_currency, quantize=False
                )
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
                    "currency": converted_cost.currency.code,
                    "cost_basis_method": position.cost_basis_method,
                }
            )

        await db.flush()
        return RealizedPnLResponse(
            period_start=period_start,
            period_end=period_end,
            total_realized_pnl=to_money(total_realized_pnl),
            total_realized_pnl_percent=Ratio.fraction_or_zero(total_realized_pnl, total_converted_cost).to_percent(),
            positions_count=len(disposed_positions),
            details=details,
        )

    async def calculate_unrealized_pnl(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
    ) -> UnrealizedPnLResponse:
        """Calculate unrealized P&L for active positions as of as_of_date."""
        eval_date = as_of_date or date.today()
        positions = (
            await db.scalars(
                select(ManagedPosition).where(
                    ManagedPosition.user_id == user_id,
                    ManagedPosition.status == PositionStatus.ACTIVE,
                )
            )
        ).all()
        if not positions:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id}")

        total_market_value = Decimal("0")
        total_cost_basis = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        details: list[dict] = []
        base_currency = await get_effective_base_currency(db, user_id=user_id)

        for position in positions:
            latest_price, converted_market, converted_cost, unrealized_pnl, unrealized_pnl_ratio = (
                await self._value_managed_position(db, position, eval_date, user_id, base_currency, quantize=False)
            )
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
                    "currency": converted_market.currency.code,
                }
            )

        await db.flush()
        return UnrealizedPnLResponse(
            as_of_date=eval_date,
            total_unrealized_pnl=to_money(total_unrealized_pnl),
            total_unrealized_pnl_percent=Ratio.fraction_or_zero(total_unrealized_pnl, total_cost_basis).to_percent(),
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
        """Insert manual MarketDataOverride records for user holdings."""
        responses: list[PriceUpdateResponse] = []
        for update in updates:
            position = await db.scalar(
                select(ManagedPosition).where(
                    ManagedPosition.user_id == user_id,
                    ManagedPosition.asset_identifier == update.asset_identifier,
                )
            )
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

            override = MarketDataOverride(
                user_id=user_id,
                asset_identifier=update.asset_identifier,
                price_date=update.price_date,
                price=update.price,
                currency=update.currency,
                source=PriceSource.MANUAL,
            )
            db.add(override)
            await db.flush()
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
        """Return overall portfolio summary including market value, cost basis, and P&L."""
        holdings = await self.get_holdings(db, user_id, as_of_date, include_disposed=True)
        total_market_value = sum((h.market_value for h in holdings), Decimal("0"))
        total_cost_basis = sum((h.cost_basis for h in holdings), Decimal("0"))
        total_unrealized_pnl = sum((h.unrealized_pnl for h in holdings), Decimal("0"))
        active_count = sum(1 for h in holdings if h.status == PositionStatus.ACTIVE)
        net_pnl_ratio = Ratio.fraction_or_zero(total_unrealized_pnl, total_cost_basis)
        currency = holdings[0].currency if holdings else await get_effective_base_currency(db, user_id=user_id)
        return PortfolioSummaryResponse(
            total_market_value=to_money(total_market_value),
            total_cost_basis=to_money(total_cost_basis),
            total_unrealized_pnl=to_money(total_unrealized_pnl),
            total_unrealized_pnl_percent=net_pnl_ratio.to_percent(),
            total_realized_pnl=Decimal("0"),
            total_realized_pnl_percent=Ratio.zero().to_percent(),
            net_pnl=to_money(total_unrealized_pnl),
            net_pnl_percent=net_pnl_ratio.to_percent(),
            holdings_count=len(holdings),
            active_positions_count=active_count,
            disposed_positions_count=len(holdings) - active_count,
            currency=currency,
        )

    async def _get_latest_price(
        self,
        db: AsyncSession,
        position: ManagedPosition,
        eval_date: date,
        user_id: UUID,
    ) -> Decimal:
        """Resolve per-unit price in position currency (override > synced price > snapshot)."""
        override = await db.scalar(
            select(MarketDataOverride).where(
                MarketDataOverride.user_id == user_id,
                MarketDataOverride.asset_identifier == position.asset_identifier,
                MarketDataOverride.price_date == eval_date,
                MarketDataOverride.source == PriceSource.MANUAL,
            )
        )
        if override:
            return override.price

        synced_price = await self._get_latest_synced_stock_price(db, position.asset_identifier, eval_date)
        if synced_price is not None:
            if synced_price.currency == position.currency:
                return synced_price.price
            return await convert_amount(
                db,
                amount=synced_price.price,
                currency=synced_price.currency,
                target_currency=position.currency,
                rate_date=eval_date,
                lazy_load=True,
            )

        snapshot = await db.scalar(
            select(AtomicPosition)
            .where(
                AtomicPosition.user_id == user_id,
                AtomicPosition.asset_identifier == position.asset_identifier,
                AtomicPosition.snapshot_date <= eval_date,
            )
            .order_by(AtomicPosition.snapshot_date.desc())
            .limit(1)
        )
        if snapshot:
            snapshot_quantity = Quantity(snapshot.quantity, PORTFOLIO_QUANTITY_UNIT).quantize()
            return snapshot.market_value / snapshot_quantity.value if not snapshot_quantity.is_zero() else snapshot.market_value

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
            .where(StockPrice.symbol == asset_identifier.strip().upper(), StockPrice.price_date <= eval_date)
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
        return latest_snapshot_date if latest_snapshot_date and latest_snapshot_date > today else today

    async def _get_latest_atomic(
        self,
        db: AsyncSession,
        asset_identifier: str,
        user_id: UUID,
    ) -> AtomicPosition | None:
        """Return latest AtomicPosition for classification fields."""
        return await db.scalar(
            select(AtomicPosition)
            .where(AtomicPosition.user_id == user_id, AtomicPosition.asset_identifier == asset_identifier)
            .order_by(AtomicPosition.snapshot_date.desc())
            .limit(1)
        )

    async def get_realized_pnl_by_asset(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        start_date: date,
        end_date: date,
        target_currency: str,
    ) -> tuple[dict[str, Decimal], set[str]]:
        """Return per-asset realized P&L and source refs from SELL transactions in [start_date, end_date]."""
        txns = (
            await db.scalars(
                select(InvestmentTransaction).where(
                    InvestmentTransaction.user_id == user_id,
                    InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL,
                    InvestmentTransaction.transaction_date >= start_date,
                    InvestmentTransaction.transaction_date <= end_date,
                )
            )
        ).all()
        by_asset: dict[str, Decimal] = {}
        source_refs: set[str] = set()
        for txn in txns:
            amount = await convert_amount(
                db, txn.realized_pnl or Decimal("0.00"), txn.currency, target_currency, txn.transaction_date, lazy_load=True
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
        """Return per-asset dividend income in [start_date, end_date] converted at payment date."""
        rows = (
            await db.execute(
                select(DividendIncome, ManagedPosition)
                .join(ManagedPosition, DividendIncome.position_id == ManagedPosition.id)
                .where(
                    DividendIncome.user_id == user_id,
                    ManagedPosition.user_id == user_id,
                    DividendIncome.payment_date >= start_date,
                    DividendIncome.payment_date <= end_date,
                )
            )
        ).all()
        by_asset: dict[str, Decimal] = {}
        for dividend, position in rows:
            amount = await convert_amount(
                db, dividend.amount, dividend.currency, target_currency, dividend.payment_date, lazy_load=True
            )
            by_asset[position.asset_identifier] = by_asset.get(position.asset_identifier, Decimal("0.00")) + amount
        return by_asset

    async def get_portfolio_summary_dashboard(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
    ) -> PortfolioSummaryDashboardResponse:
        """Build the portfolio summary dashboard with YTD realized P&L and dividend income."""
        report_date = as_of_date or date.today()
        try:
            summary = await self.get_portfolio_summary(db=db, user_id=user_id, as_of_date=as_of_date)
        except (PortfolioNotFoundError, AssetNotFoundError):
            z = Decimal("0.00")
            return PortfolioSummaryDashboardResponse(
                total_market_value=z,
                total_cost_basis=z,
                total_unrealized_pnl=z,
                total_unrealized_pnl_percent=z,
                total_realized_pnl=z,
                total_realized_pnl_percent=z,
                net_pnl=z,
                net_pnl_percent=z,
                holdings_count=0,
                active_positions_count=0,
                disposed_positions_count=0,
                currency="SGD",
                realized_pnl_ytd=z,
                dividend_income_ytd=z,
            )

        year_start = date(report_date.year, 1, 1)
        summary_currency = summary.currency.upper()
        realized_by_asset, _ = await self.get_realized_pnl_by_asset(
            db, user_id, start_date=year_start, end_date=report_date, target_currency=summary_currency
        )
        dividend_by_asset = await self.get_dividend_income_by_asset(
            db, user_id, start_date=year_start, end_date=report_date, target_currency=summary_currency
        )
        dividend_total = sum(dividend_by_asset.values(), Decimal("0.00"))
        if dividend_total == Decimal("0.00"):
            rows = await db.execute(
                select(JournalLine, Account, JournalEntry.entry_date)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .join(Account, JournalLine.account_id == Account.id)
                .where(
                    JournalEntry.user_id == user_id,
                    Account.user_id == user_id,
                    active_journal_entry_filter(JournalEntry),
                    Account.type == AccountType.INCOME,
                    func.lower(Account.name).like("%dividend%"),
                    JournalEntry.entry_date >= year_start,
                    JournalEntry.entry_date <= report_date,
                )
            )
            for line, account, entry_date in rows.all():
                ccy = (line.currency or account.currency or summary_currency).upper()
                amt = line.amount if line.direction == Direction.CREDIT else -line.amount
                dividend_total += await convert_amount(db, amt, ccy, summary_currency, entry_date, lazy_load=True)
            dividend_total = max(dividend_total, Decimal("0.00"))

        return PortfolioSummaryDashboardResponse(
            **summary.model_dump(),
            realized_pnl_ytd=to_money(sum(realized_by_asset.values(), Decimal("0.00"))),
            dividend_income_ytd=to_money(dividend_total),
        )


portfolio_service = PortfolioService()
