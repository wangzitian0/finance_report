"""Injection ports for reads whose owners still live in the app remainder.

The advisor's bounded read context includes facts whose owning domain has not
physically migrated out of ``apps/backend/src/services/`` yet:

* balance sheet / income statement / category breakdown — ``reporting``
  (contract registered, but its implementation is still inside ``services/``
  until the #1666 fold lands);
* report-package readiness — ``services/report_readiness.py`` (also #1666);
* the observed-FX-pair composer — ``services/market_data_scheduler.py``
  (cross-domain delivery-layer composition; #1610 absorbs it);
* windowed FX conversion + the income bucket classifier (used by the
  annualized-income schedule) — ``services/fx.py`` / ``services/
  reporting_calc.py`` (#1610 / #1666).

A carved package may not import ``src.services.*`` (the app-boundary gate is
shrink-only), so these reads are inverted the same way #1676 inverted
``platform → report_readiness``: the package exposes module-scoped provider
slots, and the composition root (``src/main.py`` — L4, allowed to import
everything) wires the real functions at startup; tests wire them via the
autouse fixture in ``apps/backend/tests/conftest.py``.  When #1666 / #1610
land, each port collapses into a direct published-root import plus a
``depends_on`` edge.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

#: ``(db, user_id, as_of_date=...)`` → balance-sheet dict.
BalanceSheetRead = Callable[..., Awaitable[dict[str, Any]]]
#: ``(db, user_id, start_date=..., end_date=..., currency=...)`` → income-statement dict.
IncomeStatementRead = Callable[..., Awaitable[dict[str, Any]]]
#: ``(db, user_id, breakdown_type=..., period=..., currency=...)`` → breakdown dict.
CategoryBreakdownRead = Callable[..., Awaitable[dict[str, Any]]]
#: ``(db, *, user_id)`` → report-package readiness dict.
ReadinessRead = Callable[..., Awaitable[dict[str, Any]]]
#: ``(db, user_id, *, include_default=...)`` → observed FX pairs.
FxPairsRead = Callable[..., Awaitable[list[Any]]]
#: ``(db, *, amount, currency, target_currency, rate_date, ...)`` → converted Decimal.
ConvertAmountRead = Callable[..., Awaitable[Any]]
#: ``(account_name)`` → income bucket name or None.
IncomeBucketRead = Callable[[str], str | None]

_balance_sheet: BalanceSheetRead | None = None
_income_statement: IncomeStatementRead | None = None
_category_breakdown: CategoryBreakdownRead | None = None
_reporting_error: type[Exception] | None = None
_readiness: ReadinessRead | None = None
_fx_pairs: FxPairsRead | None = None
_convert_amount: ConvertAmountRead | None = None
_fx_error: type[Exception] | None = None
_income_bucket: IncomeBucketRead | None = None


def register_reporting_reads(
    *,
    balance_sheet: BalanceSheetRead,
    income_statement: IncomeStatementRead,
    category_breakdown: CategoryBreakdownRead,
    error_type: type[Exception],
) -> None:
    """Wire the reporting-owned summary reads (and their error type)."""
    global _balance_sheet, _income_statement, _category_breakdown, _reporting_error
    _balance_sheet = balance_sheet
    _income_statement = income_statement
    _category_breakdown = category_breakdown
    _reporting_error = error_type


def register_readiness_read(provider: ReadinessRead) -> None:
    """Wire the report-package readiness read."""
    global _readiness
    _readiness = provider


def register_fx_pairs_read(provider: FxPairsRead) -> None:
    """Wire the observed-FX-pair composer read."""
    global _fx_pairs
    _fx_pairs = provider


def register_fx_conversion(*, convert_amount: ConvertAmountRead, error_type: type[Exception]) -> None:
    """Wire the windowed FX conversion (and its error type)."""
    global _convert_amount, _fx_error
    _convert_amount = convert_amount
    _fx_error = error_type


def register_income_bucket_read(provider: IncomeBucketRead) -> None:
    """Wire the income bucket classifier."""
    global _income_bucket
    _income_bucket = provider


def _require(value: Any, registrar: str) -> Any:
    if value is None:
        raise RuntimeError(
            f"advisor.extension.app_reads.{registrar}() was never called — the "
            "composition root (src/main.py) wires the real providers at startup; "
            "tests wire them via the autouse fixture in apps/backend/tests/conftest.py."
        )
    return value


def balance_sheet() -> BalanceSheetRead:
    return _require(_balance_sheet, "register_reporting_reads")


def income_statement() -> IncomeStatementRead:
    return _require(_income_statement, "register_reporting_reads")


def category_breakdown() -> CategoryBreakdownRead:
    return _require(_category_breakdown, "register_reporting_reads")


def reporting_error() -> type[Exception]:
    return _require(_reporting_error, "register_reporting_reads")


def readiness() -> ReadinessRead:
    return _require(_readiness, "register_readiness_read")


def fx_pairs() -> FxPairsRead:
    return _require(_fx_pairs, "register_fx_pairs_read")


def convert_amount() -> ConvertAmountRead:
    return _require(_convert_amount, "register_fx_conversion")


def fx_error() -> type[Exception]:
    return _require(_fx_error, "register_fx_conversion")


def income_bucket() -> IncomeBucketRead:
    return _require(_income_bucket, "register_income_bucket_read")
