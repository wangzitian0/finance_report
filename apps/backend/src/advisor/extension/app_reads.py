"""Injection ports for reads whose owners still live in the app remainder.

The advisor's bounded read context includes two facts whose owning domain has
not physically migrated out of ``apps/backend/src/services/`` yet:

* the observed-FX-pair composer — ``services/market_data_scheduler.py``
  (cross-domain delivery-layer composition; #1610 absorbs it);
* windowed FX conversion (used by the annualized-income schedule) —
  ``services/fx.py`` (also #1610).

(The reporting summary trio, report-package readiness, and the income bucket
classifier were originally ported here too, but #1666 folded their owner —
``services/reporting/`` — into the published ``src.reporting`` package while
this PR was in flight; the advisor now imports them directly from that root
instead, so those three ports were removed.)

A carved package may not import ``src.services.*`` (the app-boundary gate is
shrink-only), so these two reads are inverted the same way #1676 inverted
``platform → report_readiness``: the package exposes module-scoped provider
slots, and the composition root (``src/main.py`` — L4, allowed to import
everything) wires the real functions at startup; tests wire them via the
autouse fixture in ``apps/backend/tests/conftest.py``.  When #1610 lands,
each port collapses into a direct published-root import plus a
``depends_on`` edge.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

#: ``(db, user_id, *, include_default=...)`` → observed FX pairs.
FxPairsRead = Callable[..., Awaitable[list[Any]]]
#: ``(db, *, amount, currency, target_currency, rate_date, ...)`` → converted Decimal.
ConvertAmountRead = Callable[..., Awaitable[Any]]

_fx_pairs: FxPairsRead | None = None
_convert_amount: ConvertAmountRead | None = None
_fx_error: type[Exception] | None = None


def register_fx_pairs_read(provider: FxPairsRead) -> None:
    """Wire the observed-FX-pair composer read."""
    global _fx_pairs
    _fx_pairs = provider


def register_fx_conversion(*, convert_amount: ConvertAmountRead, error_type: type[Exception]) -> None:
    """Wire the windowed FX conversion (and its error type)."""
    global _convert_amount, _fx_error
    _convert_amount = convert_amount
    _fx_error = error_type


def _require(value: Any, registrar: str) -> Any:
    if value is None:
        raise RuntimeError(
            f"advisor.extension.app_reads.{registrar}() was never called — the "
            "composition root (src/main.py) wires the real providers at startup; "
            "tests wire them via the autouse fixture in apps/backend/tests/conftest.py."
        )
    return value


def fx_pairs() -> FxPairsRead:
    return _require(_fx_pairs, "register_fx_pairs_read")


def convert_amount() -> ConvertAmountRead:
    return _require(_convert_amount, "register_fx_conversion")


def fx_error() -> type[Exception]:
    return _require(_fx_error, "register_fx_conversion")
