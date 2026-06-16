"""Daily budget guard enforcement (EPIC-023 AC23.2.6)."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from src.llm.common import LLMBudgetExceeded, Scene, Usage
from src.llm.cost import DailyBudgetMeter

DAY = date(2026, 6, 16)
NEXT_DAY = date(2026, 6, 17)


async def test_AC23_2_6_none_limit_disables_guard():
    """AC23.2.6: a None limit never blocks."""
    meter = DailyBudgetMeter(daily_limit_usd=None)
    await meter.check_budget(today=DAY)
    await meter.record(Scene.ADVISOR_CHAT, "m", Usage(1, 1), Decimal("999"), today=DAY)
    await meter.check_budget(today=DAY)  # still fine


async def test_AC23_2_6_blocks_once_limit_reached():
    """AC23.2.6: spend at/over the daily limit raises LLMBudgetExceeded."""
    meter = DailyBudgetMeter(daily_limit_usd=Decimal("1.00"))
    await meter.check_budget(today=DAY)
    await meter.record(Scene.EXTRACTION_JSON, "m", Usage(100, 50), Decimal("1.00"), today=DAY)
    with pytest.raises(LLMBudgetExceeded):
        await meter.check_budget(today=DAY)


async def test_AC23_2_6_rolls_over_at_utc_day_boundary():
    """AC23.2.6: spend resets on a new day so a fresh day is not blocked."""
    meter = DailyBudgetMeter(daily_limit_usd=Decimal("1.00"))
    await meter.record(Scene.EXTRACTION_JSON, "m", Usage(1, 1), Decimal("1.50"), today=DAY)
    with pytest.raises(LLMBudgetExceeded):
        await meter.check_budget(today=DAY)
    # New day -> counter resets.
    await meter.check_budget(today=NEXT_DAY)
    assert meter.spent_today == Decimal("0")


async def test_AC23_2_6_default_limit_inherited_from_settings(monkeypatch):
    """AC23.2.6: omitting the limit inherits AI_DAILY_LIMIT_USD from settings."""
    from src.config import settings

    monkeypatch.setattr(settings, "ai_daily_limit_usd", 3, raising=False)
    meter = DailyBudgetMeter()  # no explicit limit -> settings
    await meter.record(Scene.EXTRACTION_JSON, "m", Usage(1, 1), Decimal("3"), today=DAY)
    with pytest.raises(LLMBudgetExceeded):
        await meter.check_budget(today=DAY)


async def test_AC23_2_6_record_ignores_unknown_cost():
    """AC23.2.6: a None cost (telemetry gap) does not corrupt the running total."""
    meter = DailyBudgetMeter(daily_limit_usd=Decimal("5"))
    await meter.record(Scene.ADVISOR_CHAT, "m", Usage(1, 1), None, today=DAY)
    assert meter.spent_today == Decimal("0")


async def test_AC23_2_6_concurrent_records_do_not_lose_increments():
    """AC23.2.6: the lock makes concurrent record() calls accumulate exactly (no lost updates)."""
    meter = DailyBudgetMeter(daily_limit_usd=None)
    n = 50

    async def one():
        await meter.record(Scene.ADVISOR_CHAT, "m", Usage(1, 1), Decimal("0.01"), today=DAY)

    await asyncio.gather(*(one() for _ in range(n)))
    assert meter.spent_today == Decimal("0.01") * n


async def test_AC23_2_6_defaults_today_to_utc_when_omitted():
    """AC23.2.6: omitting `today` uses the real UTC date (no crash, records spend)."""
    meter = DailyBudgetMeter(daily_limit_usd=Decimal("5"))
    await meter.check_budget()
    await meter.record(Scene.ADVISOR_CHAT, "m", Usage(1, 1), Decimal("1"))
    assert meter.spent_today == Decimal("1")
