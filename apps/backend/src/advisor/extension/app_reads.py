"""Injection ports for reads across a domain boundary the app-boundary gate forbids.

The advisor's bounded read context includes two facts no longer reachable by
a direct import now that ``apps/backend/src/services/`` is deleted (#1610):

* the observed-FX-pair composer — ``src.composition.observed_fx_pairs``
  (cross-domain delivery-layer composition, re-homed from the deleted
  ``services/market_data_scheduler.py`` to the composition root);
(The advisor reads only the latest frozen PackageDocument summary for report
status; it does not own or inject a readiness calculation.)

``advisor`` may not import ``src.composition`` or ``src.pricing.*`` directly
(the app-boundary gate is shrink-only), so these two reads are inverted the
same way other application-boundary reads are inverted: the package exposes
module-scoped provider slots, and the composition root (``src/main.py`` —
L4, allowed to import everything) wires the real functions at startup; tests
wire them via the autouse fixture in ``apps/backend/tests/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable
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
_fx_pairs: FxPairsRead | None = None

ReadT = TypeVar("ReadT")


def register_fx_pairs_read(provider: FxPairsRead) -> None:
    """Wire the observed-FX-pair composer read."""
    global _fx_pairs
    _fx_pairs = provider


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
