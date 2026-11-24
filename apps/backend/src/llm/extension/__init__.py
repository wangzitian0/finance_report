"""``llm.extension`` — the impure edges: the one model entry point (``agent.py``) and the reconciliation score.

``agent.py`` is the only module that calls ``infra2_sdk.runtime.create_llm_agent``.
"""

from __future__ import annotations

from src.llm.extension.semantic_scoring import ai_semantic_score

__all__ = ["ai_semantic_score"]
