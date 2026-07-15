"""Prompt-driven semantic similarity scoring (moved from ``reconciliation``, #1859).

``ai_semantic_score`` was originally defined in
``src/reconciliation/extension/scoring.py`` (EPIC-018 Phase 3), but its entire
job is "call the LLM and parse its JSON reply" — a genuine LLM call, which is
disallowed inside ``reconciliation`` (declared ``CODE-ONLY``; see
``common/meta/readme.md``'s "Cross-tier MUST rules", rule 2: a CODE-ONLY
module MUST NOT depend on an LLM client). It belongs here instead, composing
``extension.streaming``'s base-layer primitives into a higher-level
scene-agnostic helper.

Deliberately generic: this function takes an already-built ``prompt`` string
rather than reconciliation-specific parameters (transaction description /
entry memo / date diff / amount match), so it has no reason to import
anything reconciliation-owned. ``reconciliation`` already depends on ``llm``
(``depends_on=["llm", ...]``); a reverse import here would cycle the package
DAG (``check_package_contract.py``'s ``_check_no_dependency_cycle``).
Reconciliation-specific prompt construction
(``src.reconciliation.base.prompts.build_reconciliation_prompt``) stays in
``reconciliation`` and is built by the caller before invoking this function.
"""

from __future__ import annotations

import json

import src.config
from src.llm.extension.streaming import AIStreamError, accumulate_stream, stream_ai_json
from src.observability import get_logger

logger = get_logger(__name__)
settings = src.config.settings


async def ai_semantic_score(prompt: str) -> int:
    """Stream ``prompt`` through the configured AI provider; return a 0-100 score.

    ``prompt`` must instruct the model to reply with a JSON object carrying a
    ``similarity_score`` field (0-100); this function parses and clamps that
    field. Falls back gracefully to 50 (neutral) on any error — a provider
    failure, empty response, or malformed JSON never blocks the caller.
    """
    messages = [{"role": "user", "content": prompt}]

    try:
        stream = stream_ai_json(
            messages=messages,
            model=settings.primary_model,
            timeout=30.0,
        )
        content = await accumulate_stream(stream)

        if not content or not content.strip():
            logger.warning("AI semantic score returned empty response")
            return 50

        parsed = json.loads(content)
        score = int(parsed.get("similarity_score", 50))

        logger.debug(
            "AI semantic score computed",
            score=score,
            model=settings.primary_model,
        )

        return max(0, min(100, score))

    except (AIStreamError, json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        logger.warning(
            "AI semantic score failed, using fallback",
            error=str(e),
            error_type=type(e).__name__,
        )
        return 50
