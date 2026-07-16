"""Injection ports for reads across a domain boundary the app-boundary gate forbids.

The advisor's bounded read context includes two facts no longer reachable by
a direct import now that ``apps/backend/src/services/`` is deleted (#1610):

* the observed-FX-pair composer — ``src.composition.observed_fx_pairs``
  (cross-domain delivery-layer composition, re-homed from the deleted
  ``services/market_data_scheduler.py`` to the composition root);
* windowed FX conversion (used by the annualized-income schedule) —
  ``src.pricing.extension.fx.convert_amount`` (pricing's published surface,
  re-homed from the deleted ``services/fx.py``).

(The reporting summary trio, report-package readiness, and the income bucket
classifier were originally ported here too, but #1666 folded their owner —
``services/reporting/`` — into the published ``src.reporting`` package while
this PR was in flight; the advisor now imports them directly from that root
instead, so those three ports were removed.)

``advisor`` may not import ``src.composition`` or ``src.pricing.*`` directly
(the app-boundary gate is shrink-only), so these two reads are inverted the
same way #1676 inverted ``platform → report_readiness``: the package exposes
module-scoped provider slots, and the composition root (``src/main.py`` —
L4, allowed to import everything) wires the real functions at startup; tests
wire them via the autouse fixture in ``apps/backend/tests/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import date
from decimal import Decimal
from typing import Protocol, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


#: ``(db, user_id, *, include_default=...)`` → observed FX pairs.
class FxPairsRead(Protocol):
    def __call__(
        self,
        db: AsyncSession,
        user_id: UUID | None,
        *,
        include_default: bool = True,
    ) -> Awaitable[list[str]]: ...


#: ``(db, *, amount, currency, target_currency, rate_date, ...)`` → converted Decimal.
class ConvertAmountRead(Protocol):
    def __call__(
        self,
        db: AsyncSession,
        amount: Decimal,
        currency: str,
        target_currency: str,
        rate_date: date,
        *,
        average_start: date | None = None,
        average_end: date | None = None,
        fx_warnings: list[dict[str, str]] | None = None,
        lazy_load: bool = False,
    ) -> Awaitable[Decimal]: ...


_fx_pairs: FxPairsRead | None = None
_convert_amount: ConvertAmountRead | None = None
_fx_error: type[Exception] | None = None

ReadT = TypeVar("ReadT")


def register_fx_pairs_read(provider: FxPairsRead) -> None:
    """Wire the observed-FX-pair composer read."""
    global _fx_pairs
    _fx_pairs = provider


def register_fx_conversion(*, convert_amount: ConvertAmountRead, error_type: type[Exception]) -> None:
    """Wire the windowed FX conversion (and its error type)."""
    global _convert_amount, _fx_error
    _convert_amount = convert_amount
    _fx_error = error_type


def _require(value: ReadT | None, registrar: str) -> ReadT:  # noqa: UP047
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
