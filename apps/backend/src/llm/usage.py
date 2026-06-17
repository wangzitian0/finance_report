"""LLM usage statistics — request + token counts (EPIC-023).

A per-process, per-UTC-day counter of *how many LLM requests* were made and *how
many tokens* they used. There is deliberately **no cost/USD and no limit**: unit
prices and billing are provider-specific and hard to keep accurate, so spend is
out of scope — this is pure usage telemetry. Aggregation (per model/scene/day)
lives in the structured ``llm_usage`` log, which the observability stack rolls up;
the in-memory counters are a cheap running total for the current process.
"""

from __future__ import annotations

import asyncio
from datetime import date

from src.logger import get_logger

logger = get_logger(__name__)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Streaming gives no usage object and
    Z.AI/GLM rejects ``stream_options``, so token counts are estimated from text —
    approximate by design (exact counts/pricing are out of scope)."""
    return max(1, len(text) // 4) if text else 0


class LlmUsageMeter:
    """In-memory daily LLM usage counter (requests + tokens).

    ``today`` is injected (defaults to UTC date) so the rollover is testable without
    patching the clock. A lock keeps each ``record`` atomic under concurrency. Counts
    are per-process (separate workers each keep their own tally — the structured
    ``llm_usage`` log is the cross-process source of truth)."""

    def __init__(self) -> None:
        self._day: date | None = None
        self._requests = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._lock = asyncio.Lock()

    def _roll(self, today: date) -> None:
        if self._day != today:
            self._day = today
            self._requests = 0
            self._prompt_tokens = 0
            self._completion_tokens = 0

    @property
    def requests_today(self) -> int:
        return self._requests

    @property
    def tokens_today(self) -> int:
        return self._prompt_tokens + self._completion_tokens

    async def record(
        self,
        model_id: str,
        scene: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        today: date | None = None,
    ) -> None:
        """Count one LLM request and its (estimated) token usage, and log it."""
        async with self._lock:
            self._roll(today or _utc_today())
            self._requests += 1
            self._prompt_tokens += prompt_tokens
            self._completion_tokens += completion_tokens
            requests_today = self._requests
            tokens_today = self._prompt_tokens + self._completion_tokens
        logger.info(
            "llm_usage",
            scene=scene,
            model=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            requests_today=requests_today,
            tokens_today=tokens_today,
        )


def _utc_today() -> date:
    # Imported lazily so the module stays import-time pure (no clock at import).
    from datetime import UTC, datetime

    return datetime.now(UTC).date()
