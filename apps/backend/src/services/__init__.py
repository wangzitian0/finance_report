"""Lazy service package exports.

The extraction domain (pipeline, validation, dedup, brokerage, prompts,
evidence graph) moved to the ``extraction`` package (#1421) — import it via
``from src.extraction import …``, not from here.

Importing one service submodule must not eagerly import every backend service.
Tooling tests and small audit CLIs intentionally run with a reduced dependency
set, so package-level compatibility exports are resolved on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_SUBMODULES = {
    "account_service",
    "accounting",
    "ai_advisor",
    "ai_streaming",
    "allocation",
    "assets",
    "classification",
    "confidence_tier",
    "correction_service",
    "fx",
    "fx_revaluation",
    "investment_accounting",
    "market_data",
    "market_data_scheduler",
    "performance",
    "pii_redaction",
    "portfolio",
    "report_readiness",
    "reporting",
    "reporting_snapshot",
    "review_queue",
    "source_type_priority",
    "statement_parsing",
    "statement_parsing_supervisor",
    "statement_posting",
    "statement_validation",
    "storage",
    "storage_sweep",
    "workflow_events",
}

_EXPORTS: dict[str, tuple[str, str]] = {
    "AIAdvisorError": ("ai_advisor", "AIAdvisorError"),
    "AIAdvisorService": ("ai_advisor", "AIAdvisorService"),
    "AccountNotFoundError": ("account_service", "AccountNotFoundError"),
    "AccountServiceError": ("account_service", "AccountServiceError"),
    "FxRateError": ("fx", "FxRateError"),
    "ReportError": ("reporting", "ReportError"),
    "StorageError": ("storage", "StorageError"),
    "StorageService": ("storage", "StorageService"),
    "convert_amount": ("fx", "convert_amount"),
    "convert_to_base": ("fx", "convert_to_base"),
    "create_account": ("account_service", "create_account"),
    "generate_balance_sheet": ("reporting", "generate_balance_sheet"),
    "generate_cash_flow": ("reporting", "generate_cash_flow"),
    "generate_income_statement": ("reporting", "generate_income_statement"),
    "get_account": ("account_service", "get_account"),
    "get_account_trend": ("reporting", "get_account_trend"),
    "get_average_rate": ("fx", "get_average_rate"),
    "get_category_breakdown": ("reporting", "get_category_breakdown"),
    "get_exchange_rate": ("fx", "get_exchange_rate"),
    "list_accounts": ("account_service", "list_accounts"),
    "update_account": ("account_service", "update_account"),
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
