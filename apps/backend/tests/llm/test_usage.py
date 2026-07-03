"""LLM usage meter — request + token counting, no cost/limit (EPIC-023 AC23.2.6)."""

from __future__ import annotations

from datetime import date

import pytest

from src.llm.base.usage import LlmUsageMeter, estimate_tokens

pytestmark = pytest.mark.no_db

DAY = date(2026, 1, 2)
NEXT_DAY = date(2026, 1, 3)


async def test_AC23_2_6_counts_requests_and_tokens() -> None:
    """AC23.2.6: each record bumps the request count and accumulates tokens."""
    meter = LlmUsageMeter()
    await meter.record("glm-4.6v", "extraction.json", 100, 40, today=DAY)
    await meter.record("glm-4.6v", "advisor.chat", 10, 5, today=DAY)
    assert meter.requests_today == 2
    assert meter.tokens_today == 155


async def test_AC23_2_6_rolls_over_per_utc_day() -> None:
    """AC23.2.6: a new UTC day resets the running totals."""
    meter = LlmUsageMeter()
    await meter.record("m", "advisor.chat", 100, 50, today=DAY)
    assert meter.requests_today == 1
    await meter.record("m", "advisor.chat", 7, 3, today=NEXT_DAY)
    assert meter.requests_today == 1
    assert meter.tokens_today == 10


def test_estimate_tokens_is_rough_and_safe() -> None:
    """Token estimate is ~4 chars/token and never negative/zero-div."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100
