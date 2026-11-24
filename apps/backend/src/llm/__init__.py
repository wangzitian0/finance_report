"""``llm`` — the one model entry point (``extension/agent.py``), its errors and the stored-configuration ORM."""

from __future__ import annotations

from src.llm.base import (
    LLMConfigError,
    LLMError,
    ModelCallFailed,
    ModelFailureKind,
    ProtocolFamily,
    ReasoningEffort,
    Scene,
    estimate_tokens,
)
from src.llm.extension import ai_semantic_score

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly so importing the package registers the mappers on Base.metadata.
# They have no reader since #2953 stage 2; the migration that drops their tables is stage 3 (owner-reserved).
from src.llm.orm.config import LlmProvider, LlmSceneBinding

__all__ = [
    "LLMConfigError",
    "LLMError",
    "LlmProvider",
    "LlmSceneBinding",
    "ModelCallFailed",
    "ModelFailureKind",
    "ProtocolFamily",
    "ReasoningEffort",
    "Scene",
    "ai_semantic_score",
    "estimate_tokens",
]
