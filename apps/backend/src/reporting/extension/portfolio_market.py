"""Portfolio market-value adjustment lines."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency
from src.audit.quantity import Unit
from src.audit.unit_price import UnitPrice
from src.extraction.orm.layer3 import (
    ManagedPosition,
)
from src.ledger import Account, AccountType
from src.observability import get_logger
from src.portfolio import AssetNotFoundError, PortfolioService
from src.pricing import FxWarning, ManualValuationLiquidityClass, PricingError, convert_money
from src.reporting.extension._core import REPORTING_QUANTITY_UNIT, _single_source_currency
from src.reporting.extension.reporting_calc import (
    ReportError,
    _quantize_money,
)

logger = get_logger(__name__)


async def _portfolio_eval_date(db: AsyncSession, user_id: UUID, as_of_date: date) -> date:
    """Return the date on which the portfolio is valued for ``as_of_date``."""
    if as_of_date == date.today():
        return await PortfolioService()._default_holdings_eval_date(db, user_id)
    return as_of_date


def _held_on(position: ManagedPosition, eval_date: date) -> bool:
    """Return True when ``position`` is held on ``eval_date`` (same rule as the SQL filter below)."""
    return position.acquisition_date <= eval_date and (
        position.disposal_date is None or position.disposal_date > eval_date
    )


async def _load_portfolio_positions(db: AsyncSession, user_id: UUID) -> list[tuple[ManagedPosition, Account]]:
    """Return every position of the user with its broker account, for a filter per date with ``_held_on``."""
    result = await db.execute(
        select(ManagedPosition, Account)
        .join(Account, ManagedPosition.account_id == Account.id)
        .where(ManagedPosition.user_id == user_id)
        .where(Account.user_id == user_id)
    )
    return [(position, account) for position, account in result.all()]


async def _portfolio_market_basis_by_account(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    warnings: list[FxWarning] | None = None,
) -> dict[UUID, dict[str, Any]]:
    """Return converted portfolio market/cost-basis totals by broker account."""
    portfolio_eval_date = await _portfolio_eval_date(db, user_id, as_of_date)

    # Point-in-time (#1791 follow-up): a position's *current* status reflects
    # today, not portfolio_eval_date -- a position bought before and disposed
    # after this date was still held on it and must count. acquisition_date/
    # disposal_date are ManagedPosition's own validity interval, so query that
    # directly instead of the current status flag.
    result = await db.execute(
        select(ManagedPosition, Account)
        .join(Account, ManagedPosition.account_id == Account.id)
        .where(ManagedPosition.user_id == user_id)
        .where(ManagedPosition.acquisition_date <= portfolio_eval_date)
        .where(
            or_(
                ManagedPosition.disposal_date.is_(None),
                ManagedPosition.disposal_date > portfolio_eval_date,
            )
        )
        .where(Account.user_id == user_id)
    )
    return await _portfolio_basis_for_positions(
        db,
        user_id,
        [(position, account) for position, account in result.all()],
        eval_date=portfolio_eval_date,
        target_currency=target_currency,
        warnings=warnings,
    )


async def _portfolio_basis_for_positions(
    db: AsyncSession,
    user_id: UUID,
    positions: Sequence[tuple[ManagedPosition, Account]],
    *,
    eval_date: date,
    target_currency: str,
    warnings: list[FxWarning] | None = None,
) -> dict[UUID, dict[str, Any]]:
    """Value the held ``positions`` on ``eval_date`` and total them by broker account."""
    portfolio_service = PortfolioService()
    portfolio_eval_date = eval_date
    basis_by_account: dict[UUID, dict[str, Any]] = {}

    for position, account in positions:
        try:
            latest_price = await portfolio_service._get_latest_price(db, position, portfolio_eval_date, user_id)
        except AssetNotFoundError:
            logger.debug(
                "Skipping portfolio valuation without market price",
                position_id=str(position.id),
                asset_identifier=position.asset_identifier,
                as_of_date=portfolio_eval_date.isoformat(),
            )
            if warnings is not None:
                warnings.append(
                    {
                        "type": "missing_portfolio_price_as_of_date",
                        "asset_identifier": position.asset_identifier,
                        "account_id": str(position.account_id),
                        "as_of_date": portfolio_eval_date.isoformat(),
                        "message": (
                            f"No price data available for {position.asset_identifier} on or "
                            f"before {portfolio_eval_date.isoformat()}; excluded from this total."
                        ),
                    }
                )
            continue
        except PricingError as exc:
            # An FX miss inside the price lookup is a report-blocking condition,
            # same as the convert_money misses below — never a silent skip.
            raise ReportError(str(exc)) from exc

        source_currency = position.currency.upper()
        # Value/cost flow as Money; convert only when source and target currencies
        # differ (per-position values are not quantized here — accumulators are Decimal).
        position_quantity = position.quantity_qty.quantize()
        market_value = (
            UnitPrice(
                latest_price,
                Currency.of(source_currency),
                Unit.of(REPORTING_QUANTITY_UNIT),
            )
            * position_quantity
        )
        cost_basis = position.cost_basis_money
        if source_currency != target_currency.upper():
            try:
                market_value = await convert_money(
                    db, market_value, target_currency, rate_date=portfolio_eval_date, lazy_load=True
                )
                cost_basis = await convert_money(
                    db, cost_basis, target_currency, rate_date=position.acquisition_date, lazy_load=True
                )
            except PricingError as exc:
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
    warnings: list[FxWarning] | None = None,
) -> list[dict[str, Any]]:
    """Build market-value adjustment lines for active portfolio positions.

    Ledger journal lines often carry investment purchases at cost, while the
    same brokerage account can also hold cash. Portfolio snapshots carry
    current market value. Reporting includes market value minus the position
    cost basis only when that cost basis is already represented in the ledger,
    so cash balances are not accidentally netted out.
    """
    basis_by_account = await _portfolio_market_basis_by_account(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
        warnings=warnings,
    )
    return _portfolio_market_adjustment_lines_from_basis(
        basis_by_account, asset_lines=asset_lines, target_currency=target_currency
    )


def _portfolio_market_adjustment_lines_from_basis(
    basis_by_account: dict[UUID, dict[str, Any]],
    *,
    asset_lines: Sequence[dict[str, Any]],
    target_currency: str,
) -> list[dict[str, Any]]:
    """Build the market-value adjustment lines from the portfolio basis and the ledger asset lines."""
    ledger_by_account = {line["account_id"]: Decimal(str(line["amount"])) for line in asset_lines}
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
