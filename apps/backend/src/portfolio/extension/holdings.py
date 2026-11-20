"""Portfolio management service - Holdings and P&L calculations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    DataProvenance,
    ExchangeRate,
    MoneyError,
    convert as _money_convert,
    normalize_currency_code,
)
from src.audit.money import Currency, Money, to_money
from src.audit.quantity import Quantity, Unit
from src.audit.ratio import Ratio
from src.audit.unit_price import UnitPrice
from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalLine, active_journal_entry_filter
from src.observability import get_logger
from src.platform import require_base_currency
from src.portfolio.base.errors import (
    AssetNotFoundError,
    PortfolioNotFoundError,
)
from src.portfolio.orm.portfolio import (
    DividendIncome,
    InvestmentTransaction,
    InvestmentTransactionType,
    ManagedPosition,
    PositionStatus,
)
from src.pricing import (
    MarketDataOverride,
    NoObservationError,
    PrefetchedFxRates,
    PriceSource,
    PricingError,
    StockPrice,
    convert_amount,
)

if TYPE_CHECKING:
    from src.schemas.portfolio import (
        HoldingResponse,
        PortfolioSummaryDashboardResponse,
        PortfolioSummaryResponse,
    )

logger = get_logger(__name__)

PORTFOLIO_QUANTITY_UNIT = Unit("units")


def _portfolio_schemas():
    from src.schemas import portfolio as _schemas

    return _schemas


async def _account_names_by_id(
    db: AsyncSession,
    user_id: UUID,
    account_ids: set[UUID],
) -> dict[UUID, str]:
    """Resolve account display names for a set of ManagedPosition.account_ids (#1675 D4)."""
    if not account_ids:
        return {}
    rows = (
        await db.execute(
            select(Account.id, Account.name).where(Account.user_id == user_id, Account.id.in_(account_ids))
        )
    ).all()
    return {aid: name for aid, name in rows}


def _derive_provenance(source_documents: object) -> DataProvenance | None:
    """Return 'imported' only when concrete doc_id evidence exists (#868/#888)."""
    docs = source_documents.get("documents", []) if isinstance(source_documents, dict) else source_documents
    if isinstance(docs, list) and any(isinstance(doc, dict) and doc.get("doc_id") for doc in docs):
        return "imported"
    return None


def _atomic_snapshot_unit_price(snapshot: AtomicPosition) -> Decimal:
    """Derive unit price from an AtomicPosition market value and quantity."""
    snapshot_quantity = Quantity(snapshot.quantity, PORTFOLIO_QUANTITY_UNIT).quantize()
    return snapshot.market_value / snapshot_quantity.value if not snapshot_quantity.is_zero() else snapshot.market_value


def _convert_amount_with_prefetched(
    amount: Decimal,
    currency: str,
    target_currency: str,
    rate_date: date,
    fx_rates: PrefetchedFxRates,
) -> Decimal:
    """Convert amount into target_currency using prefetched FX rates."""
    source_code = normalize_currency_code(currency)
    target_code = normalize_currency_code(target_currency)
    if source_code == target_code:
        return amount
    rate = fx_rates.get_rate(source_code, target_code, rate_date)
    if rate is None:
        raise NoObservationError(f"No FX rate available for {source_code}/{target_code} on {rate_date}")
    try:
        source, target = Currency.of(source_code), Currency.of(target_code)
        return _money_convert(Money(amount, source), ExchangeRate(source, target, rate)).amount
    except MoneyError as exc:
        raise PricingError(f"invalid FX conversion boundary for {source_code}/{target_code}: {exc}") from exc


def _convert_money_with_prefetched(
    money: Money,
    target_currency: str,
    rate_date: date,
    fx_rates: PrefetchedFxRates,
) -> Money:
    """Convert Money into target_currency using prefetched FX rates."""
    converted = _convert_amount_with_prefetched(
        money.amount,
        money.currency.code,
        target_currency,
        rate_date,
        fx_rates,
    )
    return Money(converted, Currency.of(target_currency))


def _convert_pnl_with_prefetched(
    *,
    value: Money,
    value_rate_date: date,
    cost: Money,
    cost_rate_date: date,
    target_currency: str,
    fx_rates: PrefetchedFxRates,
) -> tuple[Money, Money, Money, Ratio]:
    """Convert a holding's value and cost to target_currency and derive P&L + ratio."""
    converted_value = _convert_money_with_prefetched(value, target_currency, value_rate_date, fx_rates).quantize()
    converted_cost = _convert_money_with_prefetched(cost, target_currency, cost_rate_date, fx_rates).quantize()
    pnl = converted_value - converted_cost
    return converted_value, converted_cost, pnl, Ratio.fraction_or_zero(pnl.amount, converted_cost.amount)


async def _batch_manual_overrides(
    db: AsyncSession,
    user_id: UUID,
    asset_identifiers: set[str],
    eval_date: date,
) -> dict[str, Decimal]:
    """Load manual price overrides on eval_date for a batch of asset identifiers."""
    if not asset_identifiers:
        return {}
    rows = (
        await db.execute(
            select(MarketDataOverride.asset_identifier, MarketDataOverride.price).where(
                MarketDataOverride.user_id == user_id,
                MarketDataOverride.asset_identifier.in_(asset_identifiers),
                MarketDataOverride.price_date == eval_date,
                MarketDataOverride.source == PriceSource.MANUAL,
            )
        )
    ).all()
    overrides: dict[str, Decimal] = {}
    for asset_identifier, price in rows:
        overrides.setdefault(asset_identifier, price)
    return overrides


async def _batch_latest_synced_stock_prices(
    db: AsyncSession,
    asset_identifiers: set[str],
    eval_date: date,
) -> dict[str, StockPrice]:
    """Load latest synced StockPrice on or before eval_date per normalized symbol."""
    normalized_symbols = {
        asset_identifier.strip().upper() for asset_identifier in asset_identifiers if asset_identifier.strip()
    }
    if not normalized_symbols:
        return {}
    ranked = (
        select(
            StockPrice.id,
            func.row_number()
            .over(
                partition_by=StockPrice.symbol,
                order_by=[
                    StockPrice.price_date.desc(),
                    StockPrice.created_at.desc(),
                    StockPrice.source.asc(),
                    StockPrice.currency.asc(),
                    StockPrice.id.asc(),
                ],
            )
            .label("rn"),
        )
        .where(StockPrice.symbol.in_(normalized_symbols), StockPrice.price_date <= eval_date)
        .subquery()
    )
    rows = (
        await db.scalars(select(StockPrice).join(ranked, StockPrice.id == ranked.c.id).where(ranked.c.rn == 1))
    ).all()
    return {sp.symbol: sp for sp in rows}


async def _batch_latest_atomic_positions(
    db: AsyncSession,
    user_id: UUID,
    asset_identifiers: set[str],
    *,
    max_snapshot_date: date | None = None,
) -> dict[str, AtomicPosition]:
    """Load latest AtomicPosition per asset_identifier for a user."""
    if not asset_identifiers:
        return {}
    filters = [
        AtomicPosition.user_id == user_id,
        AtomicPosition.asset_identifier.in_(asset_identifiers),
    ]
    if max_snapshot_date is not None:
        filters.append(AtomicPosition.snapshot_date <= max_snapshot_date)
    ranked = (
        select(
            AtomicPosition.id,
            func.row_number()
            .over(
                partition_by=AtomicPosition.asset_identifier,
                order_by=[
                    AtomicPosition.snapshot_date.desc(),
                    AtomicPosition.created_at.desc(),
                    AtomicPosition.id.desc(),
                ],
            )
            .label("rn"),
        )
        .where(*filters)
        .subquery()
    )
    rows = (
        await db.scalars(select(AtomicPosition).join(ranked, AtomicPosition.id == ranked.c.id).where(ranked.c.rn == 1))
    ).all()
    return {ap.asset_identifier: ap for ap in rows}


async def _batch_managed_positions_by_asset(
    db: AsyncSession,
    user_id: UUID,
    asset_identifiers: set[str],
) -> dict[str, list[ManagedPosition]]:
    """Load managed positions grouped by asset_identifier for snapshot reconciliation."""
    if not asset_identifiers:
        return {}
    rows = (
        await db.scalars(
            select(ManagedPosition)
            .where(
                ManagedPosition.user_id == user_id,
                ManagedPosition.asset_identifier.in_(asset_identifiers),
            )
            .order_by(ManagedPosition.asset_identifier, ManagedPosition.id)
        )
    ).all()
    grouped: dict[str, list[ManagedPosition]] = {}
    for position in rows:
        grouped.setdefault(position.asset_identifier, []).append(position)
    return grouped


def _resolve_managed_position_for_snapshot(
    snapshot: AtomicPosition,
    positions: Sequence[ManagedPosition],
    account_names: dict[UUID, str],
) -> ManagedPosition | None:
    """Resolve the reconciled ManagedPosition for an AtomicPosition without DB access."""
    if not positions:
        return None
    broker = (snapshot.broker or "").strip().lower()
    if broker:
        for position in positions:
            metadata_broker = str((position.position_metadata or {}).get("broker", "")).strip().lower()
            account_name = (account_names.get(position.account_id) or "").strip().lower()
            if metadata_broker == broker or account_name == broker:
                return position
    return next((p for p in positions if p.status == PositionStatus.ACTIVE), positions[0])


def _build_holding_response(
    *,
    position: ManagedPosition,
    user_id: UUID,
    asset_identifier: str,
    quantity: Decimal,
    converted_value: Money,
    converted_cost: Money,
    unrealized_pnl: Money,
    unrealized_pnl_ratio: Ratio,
    cost_money: Money,
    disposal_date: date | None,
    status: PositionStatus,
    account_names: dict[UUID, str],
    atomic: AtomicPosition | None,
) -> HoldingResponse:
    """Construct a HoldingResponse from already-converted values and metadata."""
    return _portfolio_schemas().HoldingResponse(
        id=position.id,
        user_id=user_id,
        account_id=position.account_id,
        asset_identifier=asset_identifier,
        quantity=quantity,
        cost_basis=converted_cost.amount,
        market_value=converted_value.amount,
        unrealized_pnl=unrealized_pnl.amount,
        unrealized_pnl_percent=unrealized_pnl_ratio.to_percent(),
        currency=converted_value.currency.code,
        native_cost_basis=cost_money.amount,
        native_currency=cost_money.currency.code,
        acquisition_date=position.acquisition_date,
        disposal_date=disposal_date,
        status=status,
        cost_basis_method=position.cost_basis_method,
        account_name=account_names.get(position.account_id),
        asset_type=atomic.asset_type if atomic else None,
        sector=atomic.sector if atomic else None,
        geography=atomic.geography if atomic else None,
        provenance=_derive_provenance(atomic.source_documents) if atomic else None,
    )


class PortfolioService:
    """Service for managing portfolio holdings and P&L calculations."""

    async def get_holdings(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
        include_disposed: bool = False,
        warnings: list[dict[str, str]] | None = None,
        *,
        base_currency: str | None = None,
    ) -> Sequence[HoldingResponse]:
        """Return portfolio holdings summary with market values and unrealized P&L."""
        if as_of_date is not None:
            return await self._get_snapshot_holdings(
                db,
                user_id=user_id,
                as_of_date=as_of_date,
                include_disposed=include_disposed,
                warnings=warnings,
                base_currency=base_currency,
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
        resolved_base = require_base_currency(base_currency)
        asset_identifiers = {p.asset_identifier for p in positions}

        overrides = await _batch_manual_overrides(db, user_id, asset_identifiers, eval_date)
        synced_prices = await _batch_latest_synced_stock_prices(db, asset_identifiers, eval_date)
        latest_atomics = await _batch_latest_atomic_positions(
            db, user_id, asset_identifiers, max_snapshot_date=eval_date
        )

        fx_pairs: list[tuple[str, str, date, date | None, date | None]] = []
        for position in positions:
            asset = position.asset_identifier
            override_price = overrides.get(asset)
            synced_price = synced_prices.get(asset.strip().upper()) if override_price is None else None
            latest_atomic = latest_atomics.get(asset)
            if override_price is None and synced_price is None and latest_atomic is None:
                raise AssetNotFoundError(f"No price data available for {asset} on {eval_date}")

            if synced_price is not None and synced_price.currency != position.currency:
                fx_pairs.append((synced_price.currency, position.currency, eval_date, None, None))
            if normalize_currency_code(position.currency) != resolved_base:
                fx_pairs.append((position.currency, resolved_base, eval_date, None, None))
            cost_money = position.cost_basis_money
            if cost_money.currency.code != resolved_base:
                fx_pairs.append((cost_money.currency.code, resolved_base, position.acquisition_date, None, None))

        fx_rates = PrefetchedFxRates(lazy_load=True)
        await fx_rates.prefetch(db, fx_pairs)

        holdings: list[HoldingResponse] = []
        for position in positions:
            asset = position.asset_identifier
            latest_atomic = latest_atomics.get(asset)
            if asset in overrides:
                latest_price = overrides[asset]
            elif (synced_price := synced_prices.get(asset.strip().upper())) is not None:
                latest_price = (
                    synced_price.price
                    if synced_price.currency == position.currency
                    else _convert_amount_with_prefetched(
                        synced_price.price,
                        synced_price.currency,
                        position.currency,
                        eval_date,
                        fx_rates,
                    )
                )
            else:
                assert latest_atomic is not None
                latest_price = _atomic_snapshot_unit_price(latest_atomic)

            position_quantity = position.quantity_qty.quantize()
            market_value = (
                UnitPrice(latest_price, Currency(position.currency), PORTFOLIO_QUANTITY_UNIT) * position_quantity
            )
            cost_money = position.cost_basis_money
            converted_value, converted_cost, unrealized_pnl, unrealized_pnl_ratio = _convert_pnl_with_prefetched(
                value=market_value,
                value_rate_date=eval_date,
                cost=cost_money,
                cost_rate_date=position.acquisition_date,
                target_currency=resolved_base,
                fx_rates=fx_rates,
            )
            holdings.append(
                _build_holding_response(
                    position=position,
                    user_id=position.user_id,
                    asset_identifier=asset,
                    quantity=position.quantity,
                    converted_value=converted_value,
                    converted_cost=converted_cost,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_ratio=unrealized_pnl_ratio,
                    cost_money=cost_money,
                    disposal_date=position.disposal_date,
                    status=position.status,
                    account_names=account_names,
                    atomic=latest_atomic,
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
        base_currency: str | None = None,
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

        active_snapshots: list[tuple[AtomicPosition, Quantity, PositionStatus]] = []
        for snapshot in snapshots:
            snapshot_quantity = Quantity(snapshot.quantity, PORTFOLIO_QUANTITY_UNIT).quantize()
            status = PositionStatus.DISPOSED if snapshot_quantity.is_zero() else PositionStatus.ACTIVE
            if status == PositionStatus.DISPOSED and not include_disposed:
                continue
            active_snapshots.append((snapshot, snapshot_quantity, status))

        if not active_snapshots:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id} as of {as_of_date}")

        resolved_base = require_base_currency(base_currency)
        snapshot_assets = {s.asset_identifier for s, _, _ in active_snapshots}
        managed_by_asset = await _batch_managed_positions_by_asset(db, user_id, snapshot_assets)
        candidate_account_ids = {p.account_id for pos_list in managed_by_asset.values() for p in pos_list}
        account_names = await _account_names_by_id(db, user_id, candidate_account_ids)

        reconciled: list[tuple[AtomicPosition, Quantity, PositionStatus, ManagedPosition]] = []
        for snapshot, snapshot_quantity, status in active_snapshots:
            position = _resolve_managed_position_for_snapshot(
                snapshot,
                managed_by_asset.get(snapshot.asset_identifier, ()),
                account_names,
            )
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
            reconciled.append((snapshot, snapshot_quantity, status, position))

        if not reconciled:
            raise PortfolioNotFoundError(f"No holdings found for user {user_id} as of {as_of_date}")

        synced_prices = await _batch_latest_synced_stock_prices(
            db,
            {s.asset_identifier for s, _, _, _ in reconciled},
            as_of_date,
        )

        valued: list[tuple[AtomicPosition, PositionStatus, ManagedPosition, Money, Money, date]] = []
        fx_pairs: list[tuple[str, str, date, date | None, date | None]] = []
        for snapshot, snapshot_quantity, status, position in reconciled:
            synced_price = synced_prices.get(snapshot.asset_identifier.strip().upper())
            if synced_price is not None and not snapshot_quantity.is_zero():
                market_money = (
                    UnitPrice(synced_price.price, Currency(synced_price.currency), PORTFOLIO_QUANTITY_UNIT)
                    * snapshot_quantity
                )
                cost_money, cost_rate_date = position.cost_basis_money, position.acquisition_date
            else:
                market_money = cost_money = Money(snapshot.market_value, Currency(snapshot.currency))
                cost_rate_date = as_of_date
            if market_money.currency.code != resolved_base:
                fx_pairs.append((market_money.currency.code, resolved_base, as_of_date, None, None))
            if cost_money.currency.code != resolved_base:
                fx_pairs.append((cost_money.currency.code, resolved_base, cost_rate_date, None, None))
            valued.append((snapshot, status, position, market_money, cost_money, cost_rate_date))

        fx_rates = PrefetchedFxRates(lazy_load=True)
        await fx_rates.prefetch(db, fx_pairs)

        holdings: list[HoldingResponse] = []
        for snapshot, status, position, market_money, cost_money, cost_rate_date in valued:
            converted_market_value, converted_cost_basis, unrealized_pnl, unrealized_pnl_ratio = (
                _convert_pnl_with_prefetched(
                    value=market_money,
                    value_rate_date=as_of_date,
                    cost=cost_money,
                    cost_rate_date=cost_rate_date,
                    target_currency=resolved_base,
                    fx_rates=fx_rates,
                )
            )
            holdings.append(
                _build_holding_response(
                    position=position,
                    user_id=user_id,
                    asset_identifier=snapshot.asset_identifier,
                    quantity=snapshot.quantity,
                    converted_value=converted_market_value,
                    converted_cost=converted_cost_basis,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_ratio=unrealized_pnl_ratio,
                    cost_money=cost_money,
                    disposal_date=snapshot.snapshot_date if status == PositionStatus.DISPOSED else None,
                    status=status,
                    account_names=account_names,
                    atomic=snapshot,
                )
            )

        await db.flush()
        return holdings

    async def get_portfolio_summary(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
        *,
        base_currency: str | None = None,
    ) -> PortfolioSummaryResponse:
        """Return overall portfolio summary including market value, cost basis, and P&L."""
        holdings = await self.get_holdings(db, user_id, as_of_date, include_disposed=True, base_currency=base_currency)
        active_holdings = [h for h in holdings if h.status == PositionStatus.ACTIVE]
        total_market_value = sum((h.market_value for h in active_holdings), Decimal("0"))
        total_cost_basis = sum((h.cost_basis for h in active_holdings), Decimal("0"))
        total_unrealized_pnl = sum((h.unrealized_pnl for h in active_holdings), Decimal("0"))
        active_count = len(active_holdings)
        net_pnl_ratio = Ratio.fraction_or_zero(total_unrealized_pnl, total_cost_basis)
        currency = (
            active_holdings[0].currency
            if active_holdings
            else (holdings[0].currency if holdings else require_base_currency(base_currency))
        )
        return _portfolio_schemas().PortfolioSummaryResponse(
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
            return _atomic_snapshot_unit_price(snapshot)

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
        target_code = normalize_currency_code(target_currency)
        fx_pairs: list[tuple[str, str, date, date | None, date | None]] = [
            (txn.currency, target_code, txn.transaction_date, None, None)
            for txn in txns
            if normalize_currency_code(txn.currency) != target_code
        ]
        fx_rates = PrefetchedFxRates(lazy_load=True)
        await fx_rates.prefetch(db, fx_pairs)

        by_asset: dict[str, Decimal] = {}
        source_refs: set[str] = set()
        for txn in txns:
            amount = _convert_amount_with_prefetched(
                txn.realized_pnl or Decimal("0.00"),
                txn.currency,
                target_code,
                txn.transaction_date,
                fx_rates,
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
        target_code = normalize_currency_code(target_currency)
        fx_pairs: list[tuple[str, str, date, date | None, date | None]] = [
            (str(dividend.currency), target_code, dividend.payment_date, None, None)
            for dividend, _ in rows
            if normalize_currency_code(str(dividend.currency)) != target_code
        ]
        fx_rates = PrefetchedFxRates(lazy_load=True)
        await fx_rates.prefetch(db, fx_pairs)

        by_asset: dict[str, Decimal] = {}
        for dividend, position in rows:
            amount = _convert_amount_with_prefetched(
                dividend.amount,
                dividend.currency,
                target_code,
                dividend.payment_date,
                fx_rates,
            )
            by_asset[position.asset_identifier] = by_asset.get(position.asset_identifier, Decimal("0.00")) + amount
        return by_asset

    async def get_portfolio_summary_dashboard(
        self,
        db: AsyncSession,
        user_id: UUID,
        as_of_date: date | None = None,
        *,
        base_currency: str | None = None,
    ) -> PortfolioSummaryDashboardResponse:
        """Build the portfolio summary dashboard with YTD realized P&L and dividend income."""
        report_date = as_of_date or date.today()
        resolved_base = require_base_currency(base_currency)
        try:
            summary = await self.get_portfolio_summary(
                db=db, user_id=user_id, as_of_date=as_of_date, base_currency=resolved_base
            )
        except (PortfolioNotFoundError, AssetNotFoundError):
            z = Decimal("0.00")
            return _portfolio_schemas().PortfolioSummaryDashboardResponse(
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
                currency=resolved_base,
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
            rows = (
                await db.execute(
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
            ).all()
            fx_pairs: list[tuple[str, str, date, date | None, date | None]] = [
                (
                    normalize_currency_code(str(line.currency or account.currency or summary_currency)),
                    summary_currency,
                    entry_date,
                    None,
                    None,
                )
                for line, account, entry_date in rows
                if normalize_currency_code(str(line.currency or account.currency or summary_currency))
                != summary_currency
            ]
            fx_rates = PrefetchedFxRates(lazy_load=True)
            await fx_rates.prefetch(db, fx_pairs)
            for line, account, entry_date in rows:
                ccy = (line.currency or account.currency or summary_currency).upper()
                amt = line.amount if line.direction == Direction.CREDIT else -line.amount
                dividend_total += _convert_amount_with_prefetched(amt, ccy, summary_currency, entry_date, fx_rates)
            dividend_total = max(dividend_total, Decimal("0.00"))

        return _portfolio_schemas().PortfolioSummaryDashboardResponse(
            **summary.model_dump(),
            realized_pnl_ytd=to_money(sum(realized_by_asset.values(), Decimal("0.00"))),
            dividend_income_ytd=to_money(dividend_total),
        )


portfolio_service = PortfolioService()
