"""Spend tracking + daily budget guard (EPIC-023 EPIC A).

Replaces the bare ``AI_DAILY_LIMIT_USD`` config field with an enforced
``CostMeter``: a per-process, per-UTC-day USD accumulator that refuses further
calls once the limit is hit. Single per-deployment guard — not multi-tenant
billing (that is an explicit non-goal).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from src.config import settings
from src.llm.common import LLMBudgetExceeded, Scene, Usage
from src.logger import get_logger

logger = get_logger(__name__)

_UNSET = object()


class DailyBudgetMeter:
    """In-memory daily USD budget guard implementing ``CostMeter``.

    ``today`` is injected (defaults to UTC date) so the rollover is testable
    without patching the clock. Pass ``daily_limit_usd=None`` to explicitly
    disable the guard; omit it to inherit ``AI_DAILY_LIMIT_USD`` from settings.

    Concurrency: a lock makes each ``check_budget`` / ``record`` atomic so
    concurrent calls can never lose a spend increment. It is a **best-effort**
    daily guard, not a transactional cap — because per-call cost is only known
    after the provider responds, in-flight calls that all pass ``check_budget``
    before any ``record`` can overshoot by (concurrency × per-call cost). That is
    acceptable for a daily spend ceiling; a hard cap would need reserve/commit.
    """

    def __init__(self, daily_limit_usd: Decimal | None | object = _UNSET) -> None:
        if daily_limit_usd is _UNSET:
            raw = getattr(settings, "ai_daily_limit_usd", None)
            daily_limit_usd = Decimal(str(raw)) if raw is not None else None
        self._limit: Decimal | None = daily_limit_usd  # type: ignore[assignment]
        self._day: date | None = None
        self._spent = Decimal("0")
        self._lock = asyncio.Lock()

    def _roll(self, today: date) -> None:
        if self._day != today:
            self._day = today
            self._spent = Decimal("0")

    @property
    def spent_today(self) -> Decimal:
        return self._spent

    async def check_budget(self, *, today: date | None = None) -> None:
        if self._limit is None:
            return
        async with self._lock:
            self._roll(today or _utc_today())
            if self._spent >= self._limit:
                raise LLMBudgetExceeded(
                    f"Daily AI budget of ${self._limit} reached (spent ${self._spent}); refusing further calls today."
                )

    async def record(
        self,
        scene: Scene,
        model_id: str,
        usage: Usage,
        cost_usd: Decimal | None,
        *,
        today: date | None = None,
    ) -> None:
        if cost_usd is None:
            return
        async with self._lock:
            self._roll(today or _utc_today())
            self._spent += Decimal(str(cost_usd))
        logger.info(
            "llm spend recorded",
            scene=scene.value,
            model=model_id,
            tokens=usage.total_tokens,
            cost_usd=str(cost_usd),
            spent_today=str(self._spent),
            limit_usd=str(self._limit) if self._limit is not None else None,
        )


def _utc_today() -> date:
    # Imported lazily so the module stays import-time pure (no clock at import).
    from datetime import UTC, datetime

    return datetime.now(UTC).date()
