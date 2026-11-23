"""Prompt-driven semantic similarity scoring (moved from ``reconciliation``, #1859).

``ai_semantic_score`` was originally defined in
``src/reconciliation/extension/scoring.py`` (EPIC-018 Phase 3), but its entire
job is "call the LLM and parse its JSON reply" — a genuine LLM call, which is
disallowed inside ``reconciliation`` (declared ``CODE-ONLY``; see
``common/meta/readme.md``'s "Cross-tier MUST rules", rule 2: a CODE-ONLY
module MUST NOT depend on an LLM client). It belongs here instead, calling the
one model entry point ``extension.agent.complete_text`` (#3153).

Deliberately generic: this function takes an already-built ``prompt`` string
rather than reconciliation-specific parameters (transaction description /
entry memo / date diff / amount match), so it has no reason to import
anything reconciliation-owned. ``reconciliation`` already depends on ``llm``; a
reverse import here would cycle the package DAG
(``common/meta/base/dependency_graph.py``).
Reconciliation-specific prompt construction
(``src.reconciliation.base.prompts.build_reconciliation_prompt``) stays in
``reconciliation`` and is built by the caller before invoking this function.
"""

from __future__ import annotations

import json

from infra2_sdk.runtime import DecodingSpec
from pydantic_ai.exceptions import AgentRunError

from src.llm.extension.agent import CallSite, complete_text
from src.observability import get_logger

logger = get_logger(__name__)

# GLM maps ``thinking=False`` to the lowest reasoning effort, which is what the small role used before.
_DECODING = DecodingSpec("reconciliation.semantic_score.v1", thinking=False, timeout=30.0)


async def ai_semantic_score(prompt: str) -> int:
    """Send ``prompt`` to the small model; return a 0-100 score.

    ``prompt`` must instruct the model to reply with a JSON object carrying a
    ``similarity_score`` field (0-100); this function parses and clamps that
    field. Falls back to 50 (neutral) on any error: a provider failure, an empty
    response, or malformed JSON never blocks the caller.
    """
    try:
        content = await complete_text(
            CallSite.RECONCILIATION_SEMANTIC_SCORE,
            "small",
            prompt,
            decoding=_DECODING,
        )
        if not content or not content.strip():
            logger.warning("AI semantic score returned empty response")
            return 50
        score = int(json.loads(content).get("similarity_score", 50))
        logger.debug("AI semantic score computed", score=score)
        return max(0, min(100, score))
    except (AgentRunError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        # A model failure (the SDK redacted its text: class, HTTP status, provider code), a missing key or an
        # unsupported provider (ValueError), or a reply that is not the expected JSON. Any other error, such as
        # the guard of the tests against a model call inside an open transaction, is not a fallback case.
        logger.warning("AI semantic score failed, using fallback", error=str(exc)[:300], error_type=type(exc).__name__)
        return 50
