"""Portfolio market-value adjustment lines."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.unit_price import UnitPrice
from src.models.account import Account, AccountType
from src.models.layer3 import (
    ManagedPosition,
    ManualValuationLiquidityClass,
    PositionStatus,
)
from src.observability import get_logger
from src.portfolio import AssetNotFoundError, PortfolioService
from src.services import fx
from src.services.fx import (
    FxRateError,
)
from src.services.reporting._core import REPORTING_QUANTITY_UNIT, _single_source_currency
from src.services.reporting_calc import (
    ReportError,
    _quantize_money,
)

logger = get_logger(__name__)


async def _portfolio_market_basis_by_account(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
) -> dict[UUID, dict[str, Any]]:
    """Return converted portfolio market/cost-basis totals by broker account."""
    portfolio_service = PortfolioService()
    portfolio_eval_date = as_of_date
    if as_of_date == date.today():
        portfolio_eval_date = await portfolio_service._default_holdings_eval_date(db, user_id)

    result = await db.execute(
        select(ManagedPosition, Account)
        .join(Account, ManagedPosition.account_id == Account.id)
        .where(ManagedPosition.user_id == user_id)
        .where(ManagedPosition.status == PositionStatus.ACTIVE)
        .where(Account.user_id == user_id)
        .where(Account.is_active.is_(True))
    )

    basis_by_account: dict[UUID, dict[str, Any]] = {}

    for position, account in result.all():
        try:
            latest_price = await portfolio_service._get_latest_price(db, position, portfolio_eval_date, user_id)
        except AssetNotFoundError:
            logger.debug(
                "Skipping portfolio valuation without market price",
                position_id=str(position.id),
                asset_identifier=position.asset_identifier,
                as_of_date=portfolio_eval_date.isoformat(),
            )
            continue

        source_currency = position.currency.upper()
        # Value/cost flow as Money; convert only when source and target currencies
        # differ (per-position values are not quantized here — accumulators are Decimal).
        position_quantity = position.quantity_qty.quantize()
        market_value = UnitPrice(latest_price, source_currency, REPORTING_QUANTITY_UNIT) * position_quantity
        cost_basis = position.cost_basis_money
        if source_currency != target_currency.upper():
            try:
                market_value = await fx.convert_money(
                    db, market_value, target_currency, rate_date=portfolio_eval_date, lazy_load=True
                )
                cost_basis = await fx.convert_money(
                    db, cost_basis, target_currency, rate_date=position.acquisition_date, lazy_load=True
                )
            except FxRateError as exc:
                raise ReportError(str(exc)) from exc

        basis = basis_by_account.setdefault(
            position.account_id,
            {
                "account": account,
                "market_value": Decimal("0"),
                "cost_basis": Decimal("0"),
                "source_currencies": set(),
            },
        )
        basis["market_value"] = Decimal(str(basis["market_value"])) + market_value.amount
        basis["cost_basis"] = Decimal(str(basis["cost_basis"])) + cost_basis.amount
        basis["source_currencies"].add(source_currency)

    return basis_by_account


async def _build_portfolio_market_adjustment_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    asset_lines: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build market-value adjustment lines for active portfolio positions.

    Ledger journal lines often carry investment purchases at cost, while the
    same brokerage account can also hold cash. Portfolio snapshots carry
    current market value. Reporting includes market value minus the position
    cost basis only when that cost basis is already represented in the ledger,
    so cash balances are not accidentally netted out.
    """
    ledger_by_account = {line["account_id"]: Decimal(str(line["amount"])) for line in asset_lines}
    basis_by_account = await _portfolio_market_basis_by_account(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
    )

    adjustment_lines: list[dict[str, Any]] = []
    for account_id, basis in basis_by_account.items():
        market_value = Decimal(str(basis["market_value"]))
        ledger_value = ledger_by_account.get(account_id, Decimal("0"))
        cost_basis = Decimal(str(basis["cost_basis"]))
        ledger_cost_basis = cost_basis if ledger_value >= cost_basis else Decimal("0")
        adjustment = _quantize_money(market_value - ledger_cost_basis)
        if adjustment == Decimal("0.00"):
            continue

        account = basis["account"]
        adjustment_lines.append(
            {
                "account_id": account_id,
                "name": f"{account.name} market valuation adjustment",
                "type": AccountType.ASSET,
                "parent_id": account.parent_id,
                "amount": adjustment,
                "provenance": "derived",
                "source_currency": _single_source_currency(basis["source_currencies"], target_currency),
                "allocation_asset_class": "public_equity",
                "allocation_liquidity_class": ManualValuationLiquidityClass.LIQUID.value,
                "allocation_source_type": "portfolio_market_adjustment",
            }
        )

    adjustment_lines.sort(key=lambda line: line["name"].lower())
    return adjustment_lines
