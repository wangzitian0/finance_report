"""Lazy service package exports.

The extraction domain (pipeline, validation, dedup, brokerage, prompts,
evidence graph) moved to the ``extraction`` package (#1421) — import it via
``from src.extraction import …``, not from here. The portfolio read side
(holdings/P&L, allocation, performance, report schedule) moved to the
``portfolio`` package (#1643) — import it via ``from src.portfolio import …``.
The AI advisor (chat service, guardrails, annualized income schedule) moved
to the ``advisor`` package (#1671) — import it via ``from src.advisor import …``.
The reporting implementation (statements, package readiness/traceability,
confidence metric/tier, snapshots) moved to the ``reporting`` package (#1666)
— import it via ``from src.reporting import …``. The FX lookup surface
(``fx.py``), the market-data scheduler, and the manual-valuation report
lines moved to the ``pricing`` package (#1610) — import them via
``from src.pricing import …`` (the ``observed_fx_pairs`` cross-domain
composer lives at the composition root, ``src.composition``).

No compatibility exports remain: every former ``services/`` submodule has
either moved to its owning package or (``reporting_calc.py``) lost its last
consumer and was deleted. This module is kept as an empty, importable
placeholder rather than deleted outright, since nothing currently requires
that extra step.

Importing one service submodule must not eagerly import every backend service.
Tooling tests and small audit CLIs intentionally run with a reduced dependency
set, so package-level compatibility exports are resolved on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_SUBMODULES: set[str] = set()

_EXPORTS: dict[str, tuple[str, str]] = {}

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
