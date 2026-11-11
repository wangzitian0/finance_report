"""Balance sheet generation."""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config_app import get_effective_base_currency
from src.ledger import AccountType, RevaluationError, calculate_unrealized_fx_gains
from src.observability import ErrorIds, get_logger
from src.pricing import FxWarning, PricingError, get_exchange_rate
from src.reporting.base.balance_sheet_calculator import (
    absorb_translation_rounding,
    calculate_balance_sheet_equation,
    calculate_currency_translation_adjustment,
)
from src.reporting.base.types import DEFAULT_INCLUDE_RESTRICTED
from src.reporting.extension._core import (
    _aggregate_account_provenance,
    _aggregate_balances_sql,
    _aggregate_equity_translation_variance_sql,
    _aggregate_net_income_sql,
    _build_account_lines,
    _line_total,
    _load_accounts,
)
from src.reporting.extension.portfolio_market import _build_portfolio_market_adjustment_lines
from src.reporting.extension.reporting_calc import (
    ReportError,
    _combine_provenance,
    _normalize_currency,
    _quantize_money,
)
from src.schemas.provenance import DataProvenance

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    ManualValuationLinesProvider = Callable[..., "Awaitable[tuple[list[dict], list[dict]]]"]
    ManualValuationLinesSeriesProvider = Callable[..., "Awaitable[dict[date, tuple[list[dict], list[dict]]]]"]

logger = get_logger(__name__)

_PROVIDER_MISSING_MSG = (
    "balance_sheet.register_manual_valuation_lines_provider() was never "
    "called — main.py wires it at startup (#1666); a test exercising this "
    "path without the app must call it too (the backend test conftest does)."
)
_manual_valuation_lines_provider: ManualValuationLinesProvider | None = None
_manual_valuation_lines_series_provider: ManualValuationLinesSeriesProvider | None = None


def register_manual_valuation_lines_provider(
    provider: ManualValuationLinesProvider,
    *,
    series_provider: ManualValuationLinesSeriesProvider,
) -> None:
    """Wire the manual-valuation balance-sheet-lines builders (#1666)."""
    global _manual_valuation_lines_provider, _manual_valuation_lines_series_provider
    _manual_valuation_lines_provider = provider
    _manual_valuation_lines_series_provider = series_provider


def _bind_supported_kwargs(provider: Callable[..., Any] | None, **optional_kwargs: Any) -> tuple[Callable[..., Any], dict[str, Any]]:
    if provider is None:
        raise RuntimeError(_PROVIDER_MISSING_MSG)
    non_null = {k: v for k, v in optional_kwargs.items() if v is not None}
    if not non_null:
        return provider, {}
    params = inspect.signature(provider).parameters
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    return provider, {k: v for k, v in non_null.items() if has_var_kw or k in params}


async def _build_manual_valuation_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    include_restricted: bool = DEFAULT_INCLUDE_RESTRICTED,
    warnings: list[FxWarning] | None = None,
    excluded_lines: list[dict] | None = None,
    liability_lines: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Dispatch to the registered manual-valuation lines provider."""
    provider, extra = _bind_supported_kwargs(_manual_valuation_lines_provider, liability_lines=liability_lines)
    return await provider(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
        include_restricted=include_restricted,
        warnings=warnings,
        excluded_lines=excluded_lines,
        **extra,
    )


def _excluded_holdings(excluded_lines: Sequence[dict]) -> list[dict[str, object]]:
    """Group scope-excluded manual valuation lines by asset class (#2645)."""
    grouped: dict[str, list[dict]] = {}
    for line in excluded_lines:
        grouped.setdefault(str(line["allocation_asset_class"]), []).append(line)
    rows: list[dict[str, object]] = []
    for asset_class, lines in sorted(grouped.items()):
        warnings = [line["conversion_warning"] for line in lines if line["amount"] is None]
        if warnings:
            rows.append(
                {
                    "asset_class": asset_class,
                    "total_assets": None,
                    "total_liabilities": None,
                    "net_worth": None,
                    "warnings": warnings,
                }
            )
            continue
        total_assets = sum(
            (Decimal(str(line["amount"])) for line in lines if line["type"] != AccountType.LIABILITY), Decimal("0")
        )
        total_liabilities = sum(
            (Decimal(str(line["amount"])) for line in lines if line["type"] == AccountType.LIABILITY), Decimal("0")
        )
        rows.append(
            {
                "asset_class": asset_class,
                "total_assets": _quantize_money(total_assets),
                "total_liabilities": _quantize_money(total_liabilities),
                "net_worth": _quantize_money(total_assets - total_liabilities),
                "warnings": [],
            }
        )
    return rows


async def _build_manual_valuation_lines_series(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_dates: Sequence[date],
    target_currency: str,
    include_restricted: bool = DEFAULT_INCLUDE_RESTRICTED,
    ledger_liability_names: dict[UUID, str] | None = None,
    excluded_ledger_ids_by_date: dict[date, set[UUID]] | None = None,
) -> dict[date, tuple[list[dict], list[dict]]]:
    """Dispatch to the registered manual-valuation lines series provider."""
    provider, extra = _bind_supported_kwargs(
        _manual_valuation_lines_series_provider,
        ledger_liability_names=ledger_liability_names,
        excluded_ledger_ids_by_date=excluded_ledger_ids_by_date,
    )
    return await provider(
        db,
        user_id,
        as_of_dates=as_of_dates,
        target_currency=target_currency,
        include_restricted=include_restricted,
        **extra,
    )


async def _compute_unrealized_fx_gain_loss(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    base_currency: str | None = None,
    fx_warnings: list[FxWarning] | None = None,
) -> Decimal:
    """Compute unrealized FX gain/loss in target_currency as of as_of_date."""
    normalized_target = _normalize_currency(target_currency)
    try:
        fx_revaluation = await calculate_unrealized_fx_gains(db, user_id, as_of_date, base_currency)
        raw_unrealized = fx_revaluation.total_unrealized_gain_loss
        base_curr = (
            getattr(fx_revaluation, "base_currency", None)
            or base_currency
            or await get_effective_base_currency(db, user_id=user_id)
        ).upper()
        if normalized_target != base_curr:
            try:
                rate = await get_exchange_rate(db, base_curr, normalized_target, as_of_date, lazy_load=True)
                raw_unrealized = raw_unrealized * rate
            except PricingError as exc:
                if fx_warnings is not None:
                    fx_warnings.append(
                        {
                            "type": "missing_fx_rate_target_currency",
                            "as_of_date": as_of_date.isoformat(),
                            "message": str(exc),
                        }
                    )
                logger.warning(
                    "Failed to convert unrealized FX to target currency",
                    error_id=ErrorIds.REPORT_FX_FALLBACK,
                    error=str(exc),
                )
                raw_unrealized = Decimal("0.00")
        return _quantize_money(raw_unrealized)
    except RevaluationError as exc:
        if "Missing FX rate" not in str(exc):
            raise ReportError(str(exc)) from exc
        if fx_warnings is not None:
            fx_warnings.append(
                {
                    "type": "missing_fx_revaluation_partial_skip",
                    "as_of_date": as_of_date.isoformat(),
                    "message": str(exc),
                }
            )
        logger.warning(
            "Skipping unrealized FX revaluation because FX rate is unavailable",
            error_id=ErrorIds.REPORT_FX_FALLBACK,
            as_of_date=as_of_date.isoformat(),
            error=str(exc),
        )
        return Decimal("0.00")


async def generate_balance_sheet(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    currency: str | None = None,
    include_restricted: bool = DEFAULT_INCLUDE_RESTRICTED,
    include_trust_signals: bool = True,
) -> dict[str, object]:
    """Generate balance sheet report as of a given date."""
    base_curr = (await get_effective_base_currency(db, user_id=user_id)).upper()
    target_currency = _normalize_currency(currency or base_curr)
    fx_warnings: list[FxWarning] = []
    portfolio_warnings: list[FxWarning] = []
    account_types = (AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY)
    accounts = await _load_accounts(db, user_id, account_types)
    included_ledger_currencies: set[str] = set()
    native_balances: dict[UUID, Decimal] = {}

    try:
        balances = await _aggregate_balances_sql(
            db,
            user_id,
            account_types,
            target_currency,
            as_of_date,
            base_currency=base_curr,
            fx_warnings=fx_warnings,
            included_currencies=included_ledger_currencies,
            native_balances=native_balances,
        )
    except ReportError:
        raise
    except SQLAlchemyError as exc:
        logger.error("Balance sheet aggregation failed", error_id=ErrorIds.REPORT_GENERATION_FAILED, error=str(exc))
        raise ReportError(str(exc)) from exc

    for account in accounts:
        balances.setdefault(account.id, Decimal("0"))

    provenance_by_account: dict[UUID, DataProvenance | None] = (
        await _aggregate_account_provenance(
            db, user_id, account_types, as_of_date, included_currencies=included_ledger_currencies
        )
        if include_trust_signals
        else {}
    )

    assets, liabilities, equity = (
        _build_account_lines(
            accounts,
            balances,
            acct_type,
            provenance_by_account=provenance_by_account,
            native_balances=native_balances,
        )
        for acct_type in account_types
    )
    portfolio_adjustments = await _build_portfolio_market_adjustment_lines(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
        asset_lines=assets,
        warnings=portfolio_warnings,
    )
    excluded_valuation_lines: list[dict] = []
    ledger_liabilities_before = _line_total(liabilities)
    try:
        valuation_assets, valuation_liabilities = await _build_manual_valuation_lines(
            db,
            user_id,
            as_of_date=as_of_date,
            target_currency=target_currency,
            include_restricted=include_restricted,
            warnings=portfolio_warnings,
            excluded_lines=excluded_valuation_lines,
            liability_lines=liabilities,
        )
    except PricingError as exc:
        raise ReportError(str(exc)) from exc
    excluded_ledger_liabilities = ledger_liabilities_before - _line_total(liabilities)
    assets.extend(portfolio_adjustments)
    assets.extend(valuation_assets)
    liabilities.extend(valuation_liabilities)

    total_assets = _line_total(assets)
    total_liabilities = _line_total(liabilities)
    total_equity = _line_total(equity)

    try:
        net_income_raw, pnl_translation_variance = await _aggregate_net_income_sql(
            db, user_id, target_currency, as_of_date, fx_warnings=fx_warnings
        )
    except ReportError:
        raise
    except SQLAlchemyError as exc:
        logger.error("Net income aggregation failed", error_id=ErrorIds.REPORT_GENERATION_FAILED, error=str(exc))
        raise ReportError(str(exc)) from exc

    net_income = _quantize_money(net_income_raw)
    is_presentation_currency = target_currency.upper() != base_curr
    is_multicurrency = bool(included_ledger_currencies - {target_currency})
    unrealized_fx = (
        Decimal("0.00")
        if is_presentation_currency and not is_multicurrency
        else await _compute_unrealized_fx_gain_loss(
            db,
            user_id,
            as_of_date=as_of_date,
            target_currency=target_currency,
            base_currency=base_curr,
            fx_warnings=fx_warnings,
        )
    )
    net_worth_adjustment = _quantize_money(
        _line_total(portfolio_adjustments)
        + _line_total(valuation_assets)
        - _line_total(valuation_liabilities)
        + excluded_ledger_liabilities
    )

    if is_presentation_currency and is_multicurrency:
        cta_adjustment = _quantize_money(
            total_assets - (total_liabilities + total_equity + net_income + unrealized_fx + net_worth_adjustment)
        )
    elif is_multicurrency:
        equity_translation_variance = await _aggregate_equity_translation_variance_sql(
            db, user_id, target_currency, as_of_date, base_currency=base_curr, fx_warnings=fx_warnings
        )
        cta_adjustment = calculate_currency_translation_adjustment(
            is_multicurrency=is_multicurrency,
            pnl_translation_variance=pnl_translation_variance,
            unrealized_fx=unrealized_fx,
            equity_translation_variance=equity_translation_variance,
        )
        if cta_adjustment != Decimal("0.00") or unrealized_fx != Decimal("0.00"):
            rounding_residual = calculate_balance_sheet_equation(
                total_assets=total_assets,
                total_liabilities=total_liabilities,
                total_equity=total_equity,
                net_income=net_income,
                unrealized_fx=unrealized_fx,
                net_worth_adjustment=net_worth_adjustment,
                cta_adjustment=cta_adjustment,
            ).equation_delta
            cta_adjustment = absorb_translation_rounding(
                cta_adjustment=cta_adjustment,
                residual=rounding_residual,
                rounded_figure_count=len(assets) + len(liabilities) + len(equity) + 4,
            )
    else:
        cta_adjustment = Decimal("0.00")

    totals = calculate_balance_sheet_equation(
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        net_income=net_income,
        unrealized_fx=unrealized_fx,
        net_worth_adjustment=net_worth_adjustment,
        cta_adjustment=cta_adjustment,
    )
    aggregate_provenance = _combine_provenance([line.get("provenance") for line in (*assets, *liabilities, *equity)])

    opening_balance_warnings: list[FxWarning] = []
    if include_trust_signals:
        from src.ledger import get_opening_balance_readiness

        readiness = await get_opening_balance_readiness(db, user_id)
        if readiness.get("needs_opening_balance"):
            earliest = readiness.get("earliest_activity_date")
            warning: FxWarning = {
                "type": "missing_opening_balance",
                "as_of_date": as_of_date.isoformat(),
                "message": (
                    "Activity is recorded without an opening balance, so account totals "
                    "reflect only period movement, not the starting position. Record "
                    "opening balances to trust this total."
                ),
            }
            if earliest is not None:
                warning["earliest_activity_date"] = earliest.isoformat()
            opening_balance_warnings.append(warning)

    return {
        "as_of_date": as_of_date,
        "currency": target_currency,
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "provenance": aggregate_provenance,
        "total_assets": totals.total_assets,
        "total_liabilities": totals.total_liabilities,
        "total_equity": totals.total_equity,
        "net_income": totals.net_income,
        "unrealized_fx_gain_loss": totals.unrealized_fx,
        "net_worth_adjustment_gain_loss": totals.net_worth_adjustment,
        "cta_adjustment": totals.cta_adjustment,
        "fx_warnings": fx_warnings,
        "portfolio_warnings": portfolio_warnings,
        "opening_balance_warnings": opening_balance_warnings,
        "excluded_holdings": _excluded_holdings(excluded_valuation_lines),
        "equation_delta": totals.equation_delta,
        "is_balanced": totals.is_balanced,
    }
