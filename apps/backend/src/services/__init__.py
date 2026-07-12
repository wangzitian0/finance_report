"""Lazy service package exports.

The extraction domain (pipeline, validation, dedup, brokerage, prompts,
evidence graph) moved to the ``extraction`` package (#1421) — import it via
``from src.extraction import …``, not from here. The portfolio read side
(holdings/P&L, allocation, performance, report schedule) moved to the
``portfolio`` package (#1643) — import it via ``from src.portfolio import …``.
The AI advisor (chat service, guardrails, annualized income schedule) moved
to the ``advisor`` package (#1671) — import it via ``from src.advisor import …``.

Importing one service submodule must not eagerly import every backend service.
Tooling tests and small audit CLIs intentionally run with a reduced dependency
set, so package-level compatibility exports are resolved on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_SUBMODULES = {
    "confidence_tier",
    "fx",
    "market_data_scheduler",
    "report_readiness",
    "reporting",
    "reporting_snapshot",
}

_EXPORTS: dict[str, tuple[str, str]] = {
    "FxRateError": ("fx", "FxRateError"),
    "ReportError": ("reporting", "ReportError"),
    "convert_amount": ("fx", "convert_amount"),
    "convert_to_base": ("fx", "convert_to_base"),
    "generate_balance_sheet": ("reporting", "generate_balance_sheet"),
    "generate_cash_flow": ("reporting", "generate_cash_flow"),
    "generate_income_statement": ("reporting", "generate_income_statement"),
    "get_account_trend": ("reporting", "get_account_trend"),
    "get_average_rate": ("fx", "get_average_rate"),
    "get_category_breakdown": ("reporting", "get_category_breakdown"),
    "get_exchange_rate": ("fx", "get_exchange_rate"),
}

__all__ = sorted(_SUBMODULES | set(_EXPORTS))


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module

    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = import_module(f"{__name__}.{module_name}")
        value = getattr(module, attr_name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
