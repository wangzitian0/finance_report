"""Balance sheet generation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType, RevaluationError, calculate_unrealized_fx_gains
from src.observability import ErrorIds, get_logger
from src.reporting.extension import fx_gateway
from src.reporting.extension._core import (
    _aggregate_account_confidence_tiers,
    _aggregate_account_provenance,
    _aggregate_balances_sql,
    _aggregate_net_income_sql,
    _build_account_lines,
    _line_total,
    _load_accounts,
    _strip_allocation_metadata,
)
from src.reporting.extension.fx_gateway import FxWarning
from src.reporting.extension.portfolio_market import _build_portfolio_market_adjustment_lines
from src.reporting.extension.reporting_calc import (
    ReportError,
    _combine_provenance,
    _normalize_currency,
    _quantize_money,
    _worst_confidence_tier,
)
from src.schemas.provenance import DataProvenance

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    # Always called as (db, user_id, *, as_of_date=..., target_currency=...,
    # include_restricted=...) — see _build_manual_valuation_lines below.
    ManualValuationLinesProvider = Callable[..., "Awaitable[tuple[list[dict], list[dict]]]"]

logger = get_logger(__name__)

# The manual-valuation report lines are built by
# ``src.pricing.build_manual_valuation_lines`` (#1610: re-homed from the
# retired ``services/reporting/manual_valuation.py``, the sole ``services/``
# survivor of the #1666 fold). A carved package must not import another L3
# package's implementation directly, so the builder arrives by injection —
# the same inversion as platform's readiness port (#1676): ``main.py``
# registers the real function at startup; the backend test conftest
# registers it for direct (no-app) test runs.
_manual_valuation_lines_provider: ManualValuationLinesProvider | None = None


def register_manual_valuation_lines_provider(provider: ManualValuationLinesProvider) -> None:
    """Wire the manual-valuation balance-sheet-lines builder (see note above)."""
    global _manual_valuation_lines_provider
    _manual_valuation_lines_provider = provider


async def _build_manual_valuation_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    include_restricted: bool = True,
    warnings: list[FxWarning] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Dispatch to the registered manual-valuation lines provider."""
    if _manual_valuation_lines_provider is None:
        raise RuntimeError(
            "balance_sheet.register_manual_valuation_lines_provider() was never "
            "called — main.py wires it at startup (#1666); a test exercising this "
            "path without the app must call it too (the backend test conftest does)."
        )
    return await _manual_valuation_lines_provider(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
        include_restricted=include_restricted,
        warnings=warnings,
    )


async def generate_balance_sheet(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    currency: str | None = None,
    include_restricted: bool = True,
    include_allocation_metadata: bool = False,
    include_trust_signals: bool = True,
) -> dict[str, object]:
    """Generate balance sheet report as of a given date.

    ``include_trust_signals`` gates the two extra per-account ledger scans that
    derive confidence tier and provenance. Callers that do not render per-line
    trust badges (net-worth time series, the income statement's internal balance
    sheets) pass False to avoid amplifying those scans.
    """
    target_currency = _normalize_currency(currency)
    fx_warnings: list[FxWarning] = []
    portfolio_warnings: list[FxWarning] = []
    account_types = (AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY)
    accounts = await _load_accounts(db, user_id, account_types)
    included_ledger_currencies: set[str] = set()

    try:
        balances = await _aggregate_balances_sql(
            db,
            user_id,
            account_types,
            target_currency,
            as_of_date,
            fx_warnings=fx_warnings,
            included_currencies=included_ledger_currencies,
        )
    except ReportError:
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "Balance sheet aggregation failed",
            error_id=ErrorIds.REPORT_GENERATION_FAILED,
            error=str(exc),
        )
        raise ReportError(str(exc)) from exc

    for account in accounts:
        if account.id not in balances:
            balances[account.id] = Decimal("0")

    tiers: dict[UUID, str] = {}
    provenance_by_account: dict[UUID, DataProvenance | None] = {}
    if include_trust_signals:
        tiers = await _aggregate_account_confidence_tiers(
            db,
            user_id,
            account_types,
            as_of_date,
            included_currencies=included_ledger_currencies,
        )
        provenance_by_account = await _aggregate_account_provenance(
            db,
            user_id,
            account_types,
            as_of_date,
            included_currencies=included_ledger_currencies,
        )

    assets = _build_account_lines(
        accounts,
        balances,
        AccountType.ASSET,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )
    liabilities = _build_account_lines(
        accounts,
        balances,
        AccountType.LIABILITY,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )
    equity = _build_account_lines(
        accounts,
        balances,
        AccountType.EQUITY,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )
    portfolio_adjustments = await _build_portfolio_market_adjustment_lines(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
        asset_lines=assets,
        warnings=portfolio_warnings,
    )
    try:
        valuation_assets, valuation_liabilities = await _build_manual_valuation_lines(
            db,
            user_id,
            as_of_date=as_of_date,
            target_currency=target_currency,
            include_restricted=include_restricted,
            warnings=portfolio_warnings,
        )
    except fx_gateway.FxRateError as exc:
        # pricing.build_manual_valuation_lines (registered above) raises its
        # own error family on an FX miss rather than catching internally —
        # reporting owns the ReportError mapping at this boundary, same as
        # every other fx_gateway call site in this file.
        raise ReportError(str(exc)) from exc
    assets.extend(portfolio_adjustments)
    assets.extend(valuation_assets)
    liabilities.extend(valuation_liabilities)

    total_assets = _line_total(assets)
    total_liabilities = _line_total(liabilities)
    total_equity = _line_total(equity)

    # Calculate cumulative Net Income (Income - Expenses) up to as_of_date
    # Uses period-average FX rates for consistency with the income statement
    try:
        net_income = await _aggregate_net_income_sql(
            db,
            user_id,
            target_currency,
            as_of_date,
            fx_warnings=fx_warnings,
        )
    except ReportError:
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "Net income aggregation failed",
            error_id=ErrorIds.REPORT_GENERATION_FAILED,
            error=str(exc),
        )
        raise ReportError(str(exc)) from exc

    net_income = _quantize_money(net_income)

    try:
        fx_revaluation = await calculate_unrealized_fx_gains(db, user_id, as_of_date)
        unrealized_fx = _quantize_money(fx_revaluation.total_unrealized_gain_loss)
    except RevaluationError as exc:
        if "Missing FX rate" not in str(exc):
            raise ReportError(str(exc)) from exc
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
        unrealized_fx = Decimal("0.00")
    net_worth_adjustment = _quantize_money(
        _line_total(portfolio_adjustments) + _line_total(valuation_assets) - _line_total(valuation_liabilities)
    )
    total_liab_equity_inc = total_liabilities + total_equity + net_income + unrealized_fx + net_worth_adjustment
    equation_delta = _quantize_money(total_assets - total_liab_equity_inc)

    # Net Worth / balance-sheet aggregate tier: the worst-input tier across every
    # rated line. Lines with no derivable tier (e.g. market-derived adjustments)
    # are excluded rather than counted as trusted.
    aggregate_tier = _worst_confidence_tier(line.get("confidence_tier") for line in (*assets, *liabilities, *equity))
    # Aggregate provenance: the shared provenance across rated lines, or "derived"
    # when sources mix. Mirrors the per-line provenance so the schema field is
    # populated rather than always None.
    aggregate_provenance = _combine_provenance([line.get("provenance") for line in (*assets, *liabilities, *equity)])

    # Opening-balance gate (AC2.16.4 / #1481): a balance sheet built from activity
    # with no recorded opening balance reflects only period movement, not the
    # starting position, so its total is structurally incomplete. We never let
    # such a total be presented as trusted: degrade the aggregate tier to the
    # least-trusted level and surface a warning the UI can act on. Gated behind
    # include_trust_signals so per-point net-worth time series skip the extra scan.
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
            aggregate_tier = _worst_confidence_tier([aggregate_tier, "LOW"])

    response_assets = assets if include_allocation_metadata else _strip_allocation_metadata(assets)
    response_liabilities = liabilities if include_allocation_metadata else _strip_allocation_metadata(liabilities)
    response_equity = equity if include_allocation_metadata else _strip_allocation_metadata(equity)

    return {
        "as_of_date": as_of_date,
        "currency": target_currency,
        "assets": response_assets,
        "liabilities": response_liabilities,
        "equity": response_equity,
        "confidence_tier": aggregate_tier,
        "provenance": aggregate_provenance,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "net_income": net_income,
        "unrealized_fx_gain_loss": unrealized_fx,
        "net_worth_adjustment_gain_loss": net_worth_adjustment,
        "fx_warnings": fx_warnings,
        "portfolio_warnings": portfolio_warnings,
        "opening_balance_warnings": opening_balance_warnings,
        "equation_delta": equation_delta,
        "is_balanced": abs(equation_delta) < Decimal("0.01"),
    }
